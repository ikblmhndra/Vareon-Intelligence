"""Probe read-only per provider: satu request BACA-DOANG, tanpa efek samping, tanpa nama atau nilai
secret di hasilnya (ROADMAP #23).

Dipakai dua tempat: halaman admin (`runtime_secrets.run_probe`: tes sebelum menyimpan key baru dan
tombol Test) dan CLI `tools/ops/check_secrets.py` (verifikasi sesudah rotasi di host). Dipindah ke
sini dari `tools/` karena image API tidak membawa `tools/`; CLI mengimpor dari modul ini dan tetap
menjadi pintu masuk operasional yang sama seperti sebelumnya.

Probe SINKRON (`PROBES`, httpx sync) dijalankan lewat `asyncio.to_thread` oleh `run_probe`.
AbuseIPDB dan VirusTotal memakai fungsi lookup PRODUKSI yang sama dengan enrichment
(`ioc_providers.lookup_*`) dengan indikator jinak `8.8.8.8`: tidak ada endpoint "cek key" yang
terverifikasi di dokumen vendor, dan dengan begini probe menguji persis jalur kode produksi.
Harganya SATU lookup dari kuota provider itu (AbuseIPDB 1000/hari, VirusTotal publik 500/hari),
jadi tes hanya jalan atas klik admin (dibatasi rate limit dan cooldown per provider di router),
tidak pernah otomatis.

OTX BERBEDA: endpoint lookup indikatornya publik (key palsu atau tanpa key sama-sama HTTP 200,
terbukti dengan permintaan langsung), jadi probe lewat lookup tidak akan pernah menolak key salah
ketik. Yang dipakai `GET /api/v1/users/me`, yang menjawab 403 untuk key palsu (dan tidak memakai
kuota lookup). Catatan serupa untuk LLM: `GET /models` publik di sebagian gateway (mis.
OpenRouter), jadi di sana probe membuktikan jangkauan dan keberadaan model, bukan keabsahan key.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import msal
import structlog
from cti_core.config import Settings
from cti_core.llm.client import _DEFAULT_BASE_URLS
from cti_core.runtime_secrets.registry import scrub_values

from cti_api.services import ioc_providers

log = structlog.get_logger(__name__)

PROBE_TIMEOUT_S = 15.0
PROBE_TOTAL_TIMEOUT_S = 45.0
_PROBE_IP = "8.8.8.8"


@dataclass
class Result:
    name: str
    status: str  # OK | FAIL | SKIP | NOTE
    detail: str = ""


def redact(text: str, secrets: list[str]) -> str:
    for s in secrets:
        text = text.replace(s, "***")
    return text


def _http_check(
    url: str, *, headers: dict[str, str] | None = None, timeout: float
) -> tuple[httpx.Response | None, str]:
    try:
        return httpx.get(url, headers=headers, timeout=timeout), ""
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        # `str(e)` bisa memuat URL (Telegram: token ada di path) -- cuma tipenya. `InvalidURL`
        # (token berisi newline/spasi) bukan subclass `HTTPError`.
        return None, type(e).__name__


def check_llm(settings: Any, timeout: float) -> Result:
    llm = settings.llm
    if not llm.api_key:
        return Result("llm", "FAIL", "LLM__API_KEY kosong")
    base = llm.url or _DEFAULT_BASE_URLS.get(llm.provider.lower()) or "https://api.openai.com/v1"
    r, err = _http_check(
        f"{base.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {llm.api_key}"},
        timeout=timeout,
    )
    if r is None:
        return Result("llm", "FAIL", f"{base}: {err}")
    if r.status_code != 200:
        return Result("llm", "FAIL", f"{base}: ditolak (HTTP {r.status_code}) -- key salah/dicabut")
    try:
        models = sorted(m["id"] for m in r.json()["data"])
    except (ValueError, KeyError, TypeError):
        return Result("llm", "FAIL", f"{base}: respons /models bukan format OpenAI")
    if llm.model and models and llm.model not in models:
        return Result(
            "llm", "FAIL", f"{base}: model '{llm.model}' gak ada di daftar ({len(models)} model)"
        )
    return Result("llm", "OK", f"{base} | {len(models)} model | model '{llm.model}' ada")


def check_telegram(settings: Any, timeout: float) -> Result:
    tg = settings.telegram
    if not tg.bot_token or not tg.chat_id:
        return Result("telegram", "FAIL", "BOT_TOKEN / CHAT_ID kosong")
    base = f"https://api.telegram.org/bot{tg.bot_token}"
    r, err = _http_check(f"{base}/getMe", timeout=timeout)
    if r is None:
        return Result("telegram", "FAIL", f"getMe: {err}")
    if r.status_code != 200 or not r.json().get("ok"):
        return Result(
            "telegram", "FAIL", f"getMe ditolak (HTTP {r.status_code}) -- token salah/dicabut"
        )
    bot = r.json()["result"].get("username", "?")
    r, err = _http_check(f"{base}/getChat?chat_id={tg.chat_id}", timeout=timeout)
    if r is None:
        return Result("telegram", "FAIL", f"bot @{bot} valid, getChat: {err}")
    if r.status_code != 200 or not r.json().get("ok"):
        return Result(
            "telegram",
            "FAIL",
            f"bot @{bot} valid, TAPI chat {tg.chat_id} gak bisa diakses "
            f"(HTTP {r.status_code}) -- bot belum masuk chat itu / chat_id salah",
        )
    chat = r.json()["result"]
    forum = "forum (pakai thread)" if chat.get("is_forum") else "chat biasa"
    return Result(
        "telegram", "OK", f"bot @{bot} | chat '{chat.get('title') or chat.get('type')}' ({forum})"
    )


def _optional(
    name: str, key: str, url: str, header: dict[str, str], ok_note: Any, timeout: float
) -> Result:
    if not key:
        return Result(name, "SKIP", "kosong (opsional)")
    r, err = _http_check(url, headers=header, timeout=timeout)
    if r is None:
        return Result(name, "FAIL", err)
    if r.status_code == 200:
        return Result(name, "OK", ok_note(r))
    if r.status_code == 429:
        return Result(name, "NOTE", "key diterima, tapi kena batas pemakaian (HTTP 429)")
    return Result(name, "FAIL", f"ditolak (HTTP {r.status_code}) -- key salah/dicabut")


def check_nvd(settings: Any, timeout: float) -> Result:
    return _optional(
        "nvd", settings.nvd.api_key,
        "https://services.nvd.nist.gov/rest/json/cves/2.0?resultsPerPage=1",
        {"apiKey": settings.nvd.api_key}, lambda r: "diterima", timeout,
    )  # fmt: skip


def check_github(settings: Any, timeout: float) -> Result:
    def note(r: httpx.Response) -> str:
        core = r.json().get("resources", {}).get("core", {})
        limit = core.get("limit")
        auth = (
            "terotentikasi" if limit and limit > 60 else "TOKEN DIABAIKAN (limit 60/jam = anonim)"
        )
        return f"{auth} | limit {limit}/jam, sisa {core.get('remaining')}"

    return _optional(
        "github", settings.github.token, "https://api.github.com/rate_limit",
        {"Authorization": f"Bearer {settings.github.token}"}, note, timeout,
    )  # fmt: skip


def check_twitter(settings: Any, timeout: float) -> Result:
    return _optional(
        "twitter", settings.twitter.api_key,
        "https://api.twitterapi.io/twitter/user/info?userName=twitter",
        {"X-API-Key": settings.twitter.api_key}, lambda r: "twitterapi.io menerima key", timeout,
    )  # fmt: skip


def check_x(settings: Any, timeout: float) -> Result:
    """Bearer API resmi X (sumber Twitter CADANGAN). `/2/usage/tweets` = endpoint pemakaian:
    memvalidasi bearer TANPA membaca tweet (jadi tidak ditagih). Kosong = SKIP: cadangan boleh
    belum disiapkan."""

    def note(r: httpx.Response) -> str:
        data = r.json().get("data", {})
        used, cap = data.get("project_usage"), data.get("project_cap")
        return f"X menerima bearer | pemakaian proyek {used}/{cap}"

    return _optional(
        "x", settings.x.bearer_token, "https://api.x.com/2/usage/tweets",
        {"Authorization": f"Bearer {settings.x.bearer_token}"}, note, timeout,
    )  # fmt: skip


def check_graph_token(settings: Any, timeout: float) -> Result:
    """Validasi tenant/client/secret Graph dengan SATU permintaan token (tidak membuat atau
    mengirim email, jadi tidak ada efek samping). Yang TIDAK terbukti: izin tulis ke mailbox
    pengirim; itu baru ketahuan saat draft email pertama dibuat."""
    g = settings.graph
    if not (g.tenant_id and g.client_id and g.client_secret):
        return Result("graph", "SKIP", "kosong")
    try:
        app = msal.ConfidentialClientApplication(
            g.client_id,
            authority=f"https://login.microsoftonline.com/{g.tenant_id}",
            client_credential=g.client_secret,
            timeout=timeout,
        )
        resp = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    except Exception as e:  # msal melempar ValueError untuk tenant/authority yang tidak valid
        return Result("graph", "FAIL", type(e).__name__)
    if resp.get("access_token"):
        return Result("graph", "OK", "token Azure didapat (izin mailbox pengirim tidak dites)")
    # Hanya kode galatnya: `error_description` memuat id korelasi/tenant dan bukan untuk disimpan.
    return Result("graph", "FAIL", f"ditolak: {resp.get('error', 'unknown')}")


PROBES: dict[str, Callable[[Any, float], Result]] = {
    "llm": check_llm,
    "telegram": check_telegram,
    "graph": check_graph_token,
    "nvd": check_nvd,
    "github": check_github,
    "twitter": check_twitter,
    "x": check_x,
}

_OTX_WHOAMI_URL = "https://otx.alienvault.com/api/v1/users/me"


async def _otx_whoami(http: httpx.AsyncClient, key: str) -> None:
    resp = await http.get(_OTX_WHOAMI_URL, headers={"X-OTX-API-KEY": key})
    resp.raise_for_status()


_IOC_LOOKUPS: dict[str, Callable[[httpx.AsyncClient, str], Awaitable[Any]]] = {
    "abuseipdb": lambda http, key: ioc_providers.lookup_abuseipdb(http, key, _PROBE_IP),
    "virustotal": lambda http, key: ioc_providers.lookup_virustotal(http, key, "ip", _PROBE_IP),
    "otx": _otx_whoami,
}


async def _check_ioc_provider(provider: str, settings: Any, timeout: float) -> Result:
    key = getattr(settings, provider).api_key
    if not key:
        return Result(provider, "SKIP", "kosong (opsional)")
    try:
        async with ioc_providers.make_client() as http:
            await asyncio.wait_for(_IOC_LOOKUPS[provider](http, key), timeout=timeout)
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code in (401, 403):
            return Result(provider, "FAIL", f"ditolak (HTTP {code}) -- key salah/dicabut")
        if code == 429:
            return Result(provider, "NOTE", "key diterima, tapi kena batas pemakaian (HTTP 429)")
        return Result(provider, "FAIL", f"HTTP {code}")
    except httpx.HTTPError as e:
        # Nama tipenya saja: `str(e)` bisa memuat URL, dan di beberapa vendor key ada di URL.
        return Result(provider, "FAIL", type(e).__name__)
    except TimeoutError:
        return Result(provider, "FAIL", "timeout")
    except ValueError as e:
        return Result(provider, "FAIL", f"respons tidak dikenal ({type(e).__name__})")
    if provider == "otx":
        return Result(provider, "OK", "key diterima (users/me)")
    return Result(provider, "OK", f"key diterima (satu lookup {_PROBE_IP} terpakai dari kuota)")


async def run_probe(
    provider: str, settings: Settings, *, timeout: float = PROBE_TIMEOUT_S
) -> Result:
    """Jalankan probe `provider` terhadap `settings` (boleh settings KANDIDAT yang belum disimpan).
    `KeyError` untuk provider tak dikenal. Detail hasil selalu disamarkan dengan semua secret yang
    terisi di `settings`, apa pun yang ditulis probe-nya."""
    if provider not in _IOC_LOOKUPS and provider not in PROBES:
        raise KeyError(provider)
    try:
        # Timeout httpx berlaku per fase, bukan total (Telegram dua panggilan, msal beberapa):
        # batas total supaya request admin tidak menggantung puluhan detik.
        result = await asyncio.wait_for(
            _run(provider, settings, timeout), timeout=PROBE_TOTAL_TIMEOUT_S
        )
    except TimeoutError:
        result = Result(provider, "FAIL", "timeout")
    except Exception as e:
        # Probe tidak boleh menjatuhkan request admin jadi 500 tanpa penjelasan: respons vendor yang
        # bukan JSON, key berisi karakter non-ASCII (UnicodeEncodeError) dst. Nama tipe saja: pesan
        # exception bisa memuat URL yang membawa key.
        log.warning("secret_probe_error", provider=provider, error=type(e).__name__)
        result = Result(provider, "FAIL", f"probe error ({type(e).__name__})")
    result.detail = redact(result.detail, sorted(scrub_values(settings), key=len, reverse=True))
    return result


async def _run(provider: str, settings: Settings, timeout: float) -> Result:
    if provider in _IOC_LOOKUPS:
        return await _check_ioc_provider(provider, settings, timeout)
    return await asyncio.to_thread(PROBES[provider], settings, timeout)
