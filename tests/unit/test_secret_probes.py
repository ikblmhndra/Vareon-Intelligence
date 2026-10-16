"""`cti_api.services.secret_probes` -- probe key per provider buat halaman admin (ROADMAP #23).

Probe dipindah dari `tools/ops/check_secrets.py` (image API tidak membawa `tools/`). Tes lama
`tests/unit/test_check_secrets.py` tetap jadi jaring regresi lewat CLI; di sini yang dikunci:

- probe sinkron yang dipindah berperilaku sama dan dipanggil lewat `run_probe`;
- probe Graph yang BARU: hanya mengambil token, dan yang masuk ke detail cuma KODE error
  (`error_description` AAD sering memuat potongan secret/tenant);
- AbuseIPDB dan VirusTotal memakai fungsi lookup produksi dengan indikator jinak 8.8.8.8; OTX
  TIDAK: endpoint lookup indikatornya publik (key palsu pun HTTP 200), jadi probe-nya
  `GET /api/v1/users/me`, yang menolak key palsu. Pemetaan status sama untuk ketiganya: 401/403
  ditolak, 429 hanya NOTE (key diterima tapi kena batas), selain itu FAIL;
- 429 di probe opsional (NVD, GitHub, twitterapi.io, X) juga NOTE, bukan FAIL;
- detail SELALU disamarkan (`scrub_values`) dan tidak pernah memuat pesan exception httpx (Telegram
  menaruh token di path URL); SEMUA exception probe jadi FAIL "probe error (<Tipe>)" dan ada
  batas total waktu, supaya request admin tidak jadi 500 atau menggantung.

Semua HTTP di-mock (respx), tanpa jaringan dan tanpa key asli (nilai palsu, `gitleaks:allow`).
"""

from __future__ import annotations

import re
import threading
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from cti_api.services import secret_probes
from cti_api.services.secret_probes import PROBES, Result, redact, run_probe
from cti_core.config import (
    AbuseipdbSettings,
    GithubSettings,
    GraphSettings,
    LlmSettings,
    NvdSettings,
    OtxSettings,
    Settings,
    TelegramSettings,
    TwitterSettings,
    VirustotalSettings,
    XSettings,
)
from cti_core.runtime_secrets.registry import PROVIDERS

from tests.unit.runtime_secrets_helpers import ENV_VALUES, KEYS, make_settings

LLM_KEY = "sk-probe-llm-aaaaaa"  # gitleaks:allow
TG_TOKEN = "111222333:probe-telegram-aaaaaa"  # gitleaks:allow
IOC_KEY = "probe-ioc-key-aaaaaa"  # gitleaks:allow
GRAPH_SECRET = "probe-graph-secret-aaaaaa"  # gitleaks:allow
GRAPH_TOKEN = "eyJ0probe-access-token-aaaaaa"  # gitleaks:allow
SYNC_PROVIDERS = ["llm", "telegram", "graph", "nvd", "github", "twitter", "x"]
IOC_PROVIDERS = ["otx", "abuseipdb", "virustotal"]
LOOKUP_PROVIDERS = ["abuseipdb", "virustotal"]  # lewat fungsi lookup produksi, indikator 8.8.8.8
OTX_LOOKUP_URL = "https://otx.alienvault.com/api/v1/indicators/IPv4/8.8.8.8/general"

IOC_URL = {
    "otx": "https://otx.alienvault.com/api/v1/users/me",
    "abuseipdb": "https://api.abuseipdb.com/api/v2/check",
    "virustotal": "https://www.virustotal.com/api/v3/ip_addresses/8.8.8.8",
}
IOC_KEY_HEADER = {"otx": "x-otx-api-key", "abuseipdb": "key", "virustotal": "x-apikey"}
IOC_OK_JSON: dict[str, Any] = {
    "otx": {"username": "probe-user"},
    "abuseipdb": {"data": {"abuseConfidenceScore": 0, "totalReports": 0}},
    "virustotal": {
        "data": {
            "attributes": {"last_analysis_stats": {"harmless": 70, "malicious": 0, "undetected": 5}}
        }
    },
}
IOC_BAD_SHAPE_JSON: dict[str, Any] = {
    "abuseipdb": {"errors": []},
    "virustotal": {"data": {}},
}
IOC_SETTINGS_GROUP = {
    "otx": ("otx", OtxSettings),
    "abuseipdb": ("abuseipdb", AbuseipdbSettings),
    "virustotal": ("virustotal", VirustotalSettings),
}


def ioc_settings(provider: str, key: str = IOC_KEY) -> Settings:
    name, group = IOC_SETTINGS_GROUP[provider]
    return make_settings(**{name: group(api_key=key)})


def mock_ioc(mock: respx.MockRouter, provider: str) -> respx.Route:
    return mock.get(IOC_URL[provider])


def sync_settings(**over: Any) -> Settings:
    """Semua probe sinkron punya key; `llm` menunjuk gateway lokal supaya URL-nya pasti."""
    base: dict[str, Any] = {
        "llm": LlmSettings(url="http://gw:20128/v1", api_key=LLM_KEY, model="my-combo"),
        "telegram": TelegramSettings(bot_token=TG_TOKEN, chat_id="-100123"),
    }
    return make_settings(**{**base, **over})


def mock_sync_ok(mock: respx.MockRouter) -> None:
    mock.get("http://gw:20128/v1/models").respond(
        json={"object": "list", "data": [{"id": "my-combo", "object": "model"}]}
    )
    mock.get(url__regex=r"https://api\.telegram\.org/bot.*/getMe").respond(
        json={"ok": True, "result": {"username": "probe_bot"}}
    )
    mock.get(url__regex=r"https://api\.telegram\.org/bot.*/getChat.*").respond(
        json={"ok": True, "result": {"title": "CTI Test", "is_forum": True}}
    )
    mock.get(url__regex=r"https://services\.nvd\.nist\.gov/.*").respond(json={})
    mock.get("https://api.github.com/rate_limit").respond(
        json={"resources": {"core": {"limit": 5000, "remaining": 4990}}}
    )
    mock.get(url__regex=r"https://api\.twitterapi\.io/.*").respond(json={})
    mock.get("https://api.x.com/2/usage/tweets").respond(
        json={"data": {"project_usage": "5551", "project_cap": "3000000"}}
    )


def install_msal(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any] | Exception
) -> SimpleNamespace:
    """Ganti `msal.ConfidentialClientApplication` di modul probe. Yang dicatat: argumen
    konstruktor dan `scopes` -- cukup buat memastikan probe hanya mengambil token."""
    seen = SimpleNamespace(init=[], scopes=[])

    class FakeApp:
        def __init__(
            self,
            client_id: str,
            authority: str | None = None,
            client_credential: str | None = None,
            **_: Any,
        ) -> None:
            seen.init.append(
                {
                    "client_id": client_id,
                    "authority": authority,
                    "client_credential": client_credential,
                }
            )

        def acquire_token_for_client(self, scopes: list[str], **_: Any) -> dict[str, Any]:
            seen.scopes.append(list(scopes))
            if isinstance(response, Exception):
                raise response
            return response

    monkeypatch.setattr(
        "cti_api.services.secret_probes.msal.ConfidentialClientApplication", FakeApp
    )
    return seen


def graph_settings(**over: str) -> Settings:
    fields = {
        "tenant_id": "tenant-probe-1",
        "client_id": "client-probe-1",
        "client_secret": GRAPH_SECRET,
        "sender": "cti@probe.example",
        **over,
    }
    return make_settings(graph=GraphSettings(**fields))


def blank_settings() -> Settings:
    """Semua grup provider kosong (tanpa key): probe yang jujur tidak memanggil HTTP apa pun."""
    return make_settings(**{key: Settings.model_fields[key].annotation() for key in PROVIDERS})


# --- permukaan modul --------------------------------------------------------------------------


def test_probes_cover_exactly_the_synchronous_providers() -> None:
    assert set(PROBES) == set(SYNC_PROVIDERS)
    assert all(callable(fn) for fn in PROBES.values())


def test_result_carries_name_status_and_detail() -> None:
    result = Result("nvd", "OK", "diterima")

    assert (result.name, result.status, result.detail) == ("nvd", "OK", "diterima")


def test_redact_replaces_every_secret_occurrence_with_stars() -> None:
    text = "key aaa-secret-1 dan bbb-secret-2 lalu aaa-secret-1 lagi"

    assert redact(text, ["aaa-secret-1", "bbb-secret-2"]) == "key *** dan *** lalu *** lagi"


def test_redact_without_secrets_returns_the_text_unchanged() -> None:
    assert redact("tidak ada apa-apa", []) == "tidak ada apa-apa"


# --- probe sinkron yang dipindah: perilaku sama -----------------------------------------------


def test_llm_probe_is_ok_when_the_gateway_lists_the_configured_model() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_sync_ok(mock)

        result = secret_probes.check_llm(sync_settings(), 5.0)

    assert result.status == "OK"
    assert "my-combo" in result.detail


def test_llm_probe_fails_when_the_model_is_missing_from_the_gateway() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://gw:20128/v1/models").respond(json={"data": [{"id": "lain"}]})

        result = secret_probes.check_llm(sync_settings(), 5.0)

    assert result.status == "FAIL"
    assert "my-combo" in result.detail


def test_llm_probe_fails_without_an_api_key_and_sends_nothing() -> None:
    settings = sync_settings(llm=LlmSettings(url="http://gw:20128/v1", api_key=""))
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("http://gw:20128/v1/models")

        result = secret_probes.check_llm(settings, 5.0)

    assert result.status == "FAIL"
    assert not route.called


def test_llm_probe_reports_a_rejected_key() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://gw:20128/v1/models").respond(401)

        result = secret_probes.check_llm(sync_settings(), 5.0)

    assert result.status == "FAIL"
    assert "ditolak (HTTP 401)" in result.detail


def test_telegram_probe_is_ok_when_the_bot_and_the_chat_are_reachable() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_sync_ok(mock)

        result = secret_probes.check_telegram(sync_settings(), 5.0)

    assert result.status == "OK"
    assert "@probe_bot" in result.detail


def test_telegram_probe_reports_a_rejected_token() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://api\.telegram\.org/bot.*/getMe").respond(401)

        result = secret_probes.check_telegram(sync_settings(), 5.0)

    assert result.status == "FAIL"
    assert "ditolak (HTTP 401)" in result.detail


def test_telegram_probe_error_detail_has_the_exception_type_never_the_url() -> None:
    """httpx menaruh URL (token di path) di pesan exception: yang boleh keluar cuma tipenya."""
    boom = httpx.ConnectError(f"boom https://api.telegram.org/bot{TG_TOKEN}/getMe")
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://api\.telegram\.org/bot.*/getMe").mock(side_effect=boom)

        result = secret_probes.check_telegram(sync_settings(), 5.0)

    assert result.status == "FAIL"
    assert "ConnectError" in result.detail
    assert TG_TOKEN not in result.detail


def test_telegram_probe_survives_a_token_that_makes_the_url_invalid() -> None:
    """Token hasil paste dengan newline membuat URL tidak valid (`httpx.InvalidURL`, bukan
    subclass `HTTPError`): harus jadi FAIL bernama tipe, bukan exception."""
    token = "111222333:probe" + chr(10) + "telegram-aaaaaa"  # gitleaks:allow
    settings = sync_settings(telegram=TelegramSettings(bot_token=token, chat_id="-100123"))
    with respx.mock(assert_all_called=False):
        result = secret_probes.check_telegram(settings, 5.0)

    assert result.status == "FAIL"
    assert "InvalidURL" in result.detail
    assert "telegram-aaaaaa" not in result.detail


OPTIONAL_PROBES = [
    pytest.param(
        "nvd",
        lambda key: NvdSettings(api_key=key),
        r"https://services\.nvd\.nist\.gov/.*",
        id="nvd",
    ),
    pytest.param(
        "github",
        lambda key: GithubSettings(token=key),
        r"https://api\.github\.com/rate_limit",
        id="github",
    ),
    pytest.param(
        "twitter",
        lambda key: TwitterSettings(api_key=key),
        r"https://api\.twitterapi\.io/.*",
        id="twitter",
    ),
    pytest.param(
        "x",
        lambda key: XSettings(bearer_token=key),
        r"https://api\.x\.com/2/usage/tweets",
        id="x",
    ),
]


@pytest.mark.parametrize(("provider", "group", "url_regex"), OPTIONAL_PROBES)
def test_optional_probe_is_ok_when_the_provider_accepts_the_key(
    provider: str, group: Any, url_regex: str
) -> None:
    settings = sync_settings(**{provider: group(IOC_KEY)})
    with respx.mock(assert_all_called=False) as mock:
        mock_sync_ok(mock)

        result = getattr(secret_probes, f"check_{provider}")(settings, 5.0)

    assert result.status == "OK"


@pytest.mark.parametrize(("provider", "group", "url_regex"), OPTIONAL_PROBES)
def test_optional_probe_fails_when_the_provider_rejects_the_key(
    provider: str, group: Any, url_regex: str
) -> None:
    settings = sync_settings(**{provider: group(IOC_KEY)})
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=url_regex).respond(401)

        result = getattr(secret_probes, f"check_{provider}")(settings, 5.0)

    assert result.status == "FAIL"
    assert "HTTP 401" in result.detail


@pytest.mark.parametrize(("provider", "group", "url_regex"), OPTIONAL_PROBES)
def test_optional_probe_reports_rate_limiting_as_a_note_not_a_failure(
    provider: str, group: Any, url_regex: str
) -> None:
    """429 berarti key dikenali tapi kuota habis; FAIL di sini akan menolak key yang benar."""
    settings = sync_settings(**{provider: group(IOC_KEY)})
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=url_regex).respond(429)

        result = getattr(secret_probes, f"check_{provider}")(settings, 5.0)

    assert result.status == "NOTE"
    assert "HTTP 429" in result.detail


@pytest.mark.parametrize(("provider", "group", "url_regex"), OPTIONAL_PROBES)
@pytest.mark.parametrize("status", [403, 500])
def test_optional_probe_rejects_any_status_other_than_200_and_429(
    provider: str, group: Any, url_regex: str, status: int
) -> None:
    settings = sync_settings(**{provider: group(IOC_KEY)})
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=url_regex).respond(status)

        result = getattr(secret_probes, f"check_{provider}")(settings, 5.0)

    assert result.status == "FAIL"
    assert f"ditolak (HTTP {status}) -- key salah/dicabut" in result.detail


@pytest.mark.parametrize(("provider", "group", "url_regex"), OPTIONAL_PROBES)
def test_optional_probe_skips_an_empty_key_without_any_request(
    provider: str, group: Any, url_regex: str
) -> None:
    settings = sync_settings(**{provider: group("")})
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(url__regex=url_regex)

        result = getattr(secret_probes, f"check_{provider}")(settings, 5.0)

    assert result.status == "SKIP"
    assert not route.called


# --- probe Graph: hanya mengambil token -------------------------------------------------------


@pytest.mark.parametrize("blank", ["tenant_id", "client_id", "client_secret"])
def test_graph_probe_skips_when_the_tenant_client_or_secret_is_blank(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    seen = install_msal(monkeypatch, {"access_token": GRAPH_TOKEN})

    result = secret_probes.check_graph_token(graph_settings(**{blank: ""}), 5.0)

    assert result.status == "SKIP"
    assert seen.init == []  # tidak ada aplikasi MSAL yang dibuat


def test_graph_probe_acquires_a_token_with_the_configured_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = install_msal(monkeypatch, {"access_token": GRAPH_TOKEN})

    secret_probes.check_graph_token(graph_settings(), 5.0)

    assert seen.init == [
        {
            "client_id": "client-probe-1",
            "authority": "https://login.microsoftonline.com/tenant-probe-1",
            "client_credential": GRAPH_SECRET,
        }
    ]
    assert seen.scopes == [["https://graph.microsoft.com/.default"]]


def test_graph_probe_is_ok_when_a_token_is_issued_and_never_shows_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_msal(monkeypatch, {"access_token": GRAPH_TOKEN, "token_type": "Bearer"})

    result = secret_probes.check_graph_token(graph_settings(), 5.0)

    assert result.status == "OK"
    assert GRAPH_TOKEN not in result.detail
    assert GRAPH_SECRET not in result.detail


def test_graph_probe_does_not_need_a_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    """Probe hanya memvalidasi kredensial aplikasi; pengirim bukan bagian yang diganti dari UI."""
    install_msal(monkeypatch, {"access_token": GRAPH_TOKEN})

    result = secret_probes.check_graph_token(graph_settings(sender=""), 5.0)

    assert result.status == "OK"


def test_graph_probe_fails_with_the_error_code_only(monkeypatch: pytest.MonkeyPatch) -> None:
    leak = f"AADSTS7000215: Invalid client secret provided {GRAPH_SECRET} tenant tenant-probe-1"
    install_msal(monkeypatch, {"error": "invalid_client", "error_description": leak})

    result = secret_probes.check_graph_token(graph_settings(), 5.0)

    assert result.status == "FAIL"
    assert "invalid_client" in result.detail
    assert "AADSTS7000215" not in result.detail
    assert "Invalid client secret" not in result.detail
    assert GRAPH_SECRET not in result.detail


def test_graph_probe_names_only_the_type_when_msal_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """MSAL melempar `ValueError` buat tenant/authority yang tidak valid; pesannya memuat URL."""
    boom = ValueError(
        f"bad authority https://login.microsoftonline.com/tenant-probe-1 {GRAPH_SECRET}"
    )
    install_msal(monkeypatch, boom)

    result = secret_probes.check_graph_token(graph_settings(), 5.0)

    assert result.status == "FAIL"
    assert "ValueError" in result.detail
    assert "tenant-probe-1" not in result.detail
    assert GRAPH_SECRET not in result.detail


def test_graph_probe_fails_when_the_response_has_neither_a_token_nor_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_msal(monkeypatch, {})

    result = secret_probes.check_graph_token(graph_settings(), 5.0)

    assert result.status == "FAIL"


# --- run_probe: provider sinkron --------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["llm", "telegram", "nvd", "github", "twitter", "x"])
async def test_run_probe_maps_each_synchronous_provider_to_its_own_check(provider: str) -> None:
    """Hanya URL milik provider itu yang di-mock: probe yang tertukar memanggil URL lain dan
    ditolak respx."""
    with respx.mock(assert_all_called=False) as mock:
        mock_sync_ok(mock)

        result = await run_probe(provider, sync_settings())

    assert result.status == "OK"
    assert result.name == provider


@pytest.mark.asyncio
async def test_run_probe_graph_uses_the_token_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    install_msal(monkeypatch, {"access_token": GRAPH_TOKEN})

    result = await run_probe("graph", graph_settings())

    assert result.status == "OK"
    assert result.name == "graph"


@pytest.mark.asyncio
async def test_run_probe_runs_a_synchronous_probe_off_the_event_loop_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probe sinkron memblokir (`httpx.get`) dan dipanggil dari handler async API."""
    seen: dict[str, Any] = {}

    def spy(settings: Settings, timeout: float) -> Result:
        seen.update(thread=threading.get_ident(), settings=settings, timeout=timeout)
        return Result("nvd", "OK", "diterima")

    monkeypatch.setitem(PROBES, "nvd", spy)
    settings = make_settings()

    await run_probe("nvd", settings, timeout=3.5)

    assert seen["thread"] != threading.get_ident()
    assert seen["settings"] is settings
    assert seen["timeout"] == 3.5


@pytest.mark.asyncio
async def test_run_probe_default_timeout_is_15_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []

    def spy(settings: Settings, timeout: float) -> Result:
        seen.append(timeout)
        return Result("nvd", "OK", "")

    monkeypatch.setitem(PROBES, "nvd", spy)

    await run_probe("nvd", make_settings())

    assert seen == [15.0]


@pytest.mark.asyncio
async def test_run_probe_returns_the_probe_result_for_a_synchronous_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROBES, "nvd", lambda settings, timeout: Result("nvd", "NOTE", "catatan"))

    result = await run_probe("nvd", make_settings())

    assert (result.name, result.status, result.detail) == ("nvd", "NOTE", "catatan")


# --- run_probe: exception dan batas waktu ----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        ValueError(f"respons aneh memuat {IOC_KEY}"),
        UnicodeEncodeError("ascii", "kunci-" + chr(0xF1), 6, 7, "ordinal not in range(128)"),
        RuntimeError(f"https://api.telegram.org/bot{TG_TOKEN}/getMe"),
    ],
    ids=["value-error", "unicode-encode-error", "runtime-error"],
)
async def test_run_probe_turns_any_probe_exception_into_a_named_failure_not_a_raise(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """Key non-ASCII di header, respons vendor yang bukan JSON, dst. jangan jadi 500 di halaman
    admin; nama tipe saja, karena pesan exception bisa memuat URL atau key."""

    def boom(settings: Settings, timeout: float) -> Result:
        raise error

    monkeypatch.setitem(PROBES, "nvd", boom)

    result = await run_probe("nvd", make_settings())

    assert result.status == "FAIL"
    assert result.detail == f"probe error ({type(error).__name__})"
    assert IOC_KEY not in result.detail
    assert TG_TOKEN not in result.detail


@pytest.mark.asyncio
async def test_run_probe_gives_up_after_the_total_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout httpx berlaku per fase, bukan total: Telegram dua panggilan, MSAL beberapa."""
    release = threading.Event()

    def slow(settings: Settings, timeout: float) -> Result:
        release.wait(5)
        return Result("nvd", "OK", "terlambat")

    monkeypatch.setitem(PROBES, "nvd", slow)
    monkeypatch.setattr(secret_probes, "PROBE_TOTAL_TIMEOUT_S", 0.05)
    try:
        result = await run_probe("nvd", make_settings())
    finally:
        release.set()  # lepaskan thread yang masih menunggu

    assert result.status == "FAIL"
    assert result.detail == "timeout"


def test_the_total_probe_timeout_is_45_seconds() -> None:
    assert secret_probes.PROBE_TOTAL_TIMEOUT_S == 45.0


# --- run_probe: detail selalu disamarkan ------------------------------------------------------


@pytest.mark.asyncio
async def test_run_probe_redacts_every_known_secret_from_a_synchronous_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Satu daftar buat semua (`scrub_values`): key provider mana pun, JWT secret, dan master key
    tidak boleh lolos walau probe-nya sendiri ceroboh memantulkannya."""
    settings = make_settings(keys=KEYS)
    leaked = [
        ENV_VALUES[("nvd", "api_key")],
        ENV_VALUES[("otx", "api_key")],
        "jwt-env-aaaaaa",
        KEYS,
    ]
    detail = "bocor: " + " | ".join(leaked)
    monkeypatch.setitem(PROBES, "nvd", lambda s, t: Result("nvd", "FAIL", detail))

    result = await run_probe("nvd", settings)

    for value in leaked:
        assert value not in result.detail
    assert "***" in result.detail


@pytest.mark.asyncio
async def test_run_probe_redacts_a_secret_that_telegram_echoes_in_a_synchronous_detail() -> None:
    boom = httpx.ConnectError(f"boom https://api.telegram.org/bot{TG_TOKEN}/getMe")
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://api\.telegram\.org/bot.*/getMe").mock(side_effect=boom)

        result = await run_probe("telegram", sync_settings())

    assert result.status == "FAIL"
    assert TG_TOKEN not in result.detail
    assert "ConnectError" in result.detail


# --- run_probe: semua provider registry tertangani --------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", list(PROVIDERS))
async def test_run_probe_handles_every_registry_provider_without_a_key(provider: str) -> None:
    """Tanpa key tidak boleh ada HTTP sama sekali (respx menolak request yang tidak di-mock) dan
    tidak ada provider registry yang jatuh ke `KeyError`."""
    with respx.mock(assert_all_called=False):
        result = await run_probe(provider, blank_settings())

    expected = "FAIL" if provider in {"llm", "telegram"} else "SKIP"
    assert result.status == expected
    assert result.name == provider


@pytest.mark.asyncio
async def test_run_probe_raises_key_error_for_an_unknown_provider() -> None:
    with pytest.raises(KeyError):
        await run_probe("tidak-ada", make_settings())


# --- run_probe: OTX, AbuseIPDB, VirusTotal ----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", IOC_PROVIDERS)
async def test_ioc_probe_is_ok_when_the_lookup_succeeds(provider: str) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_ioc(mock, provider).respond(json=IOC_OK_JSON[provider])

        result = await run_probe(provider, ioc_settings(provider))

    assert result.status == "OK"
    assert result.name == provider


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", LOOKUP_PROVIDERS)
async def test_ioc_probe_looks_up_the_benign_ip_with_the_key_it_was_given(provider: str) -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock_ioc(mock, provider).respond(json=IOC_OK_JSON[provider])

        await run_probe(provider, ioc_settings(provider))

    assert route.call_count == 1
    request = route.calls[0].request
    assert request.method == "GET"
    assert "8.8.8.8" in str(request.url)
    assert request.headers[IOC_KEY_HEADER[provider]] == IOC_KEY


@pytest.mark.asyncio
async def test_otx_probe_calls_users_me_with_the_key_and_looks_up_no_indicator() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock_ioc(mock, "otx").respond(json=IOC_OK_JSON["otx"])

        await run_probe("otx", ioc_settings("otx"))

    assert route.call_count == 1
    request = route.calls[0].request
    assert request.method == "GET"
    assert request.url.path == "/api/v1/users/me"
    assert "8.8.8.8" not in str(request.url)
    assert request.headers[IOC_KEY_HEADER["otx"]] == IOC_KEY


@pytest.mark.asyncio
async def test_otx_probe_rejects_a_wrong_key_even_though_the_public_lookup_answers_200() -> None:
    """Endpoint lookup indikator OTX publik: probe lewat lookup tidak akan pernah menolak key
    salah ketik. Probe harus memakai endpoint yang memeriksa key."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(OTX_LOOKUP_URL).respond(json=IOC_OK_JSON["otx"])
        mock_ioc(mock, "otx").respond(403)

        result = await run_probe("otx", ioc_settings("otx"))

    assert result.status == "FAIL"
    assert "ditolak (HTTP 403)" in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", IOC_PROVIDERS)
async def test_ioc_probe_says_the_key_was_accepted_when_it_is_ok(provider: str) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_ioc(mock, provider).respond(json=IOC_OK_JSON[provider])

        result = await run_probe(provider, ioc_settings(provider))

    assert "key diterima" in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", LOOKUP_PROVIDERS)
async def test_a_lookup_probe_ok_detail_tells_the_admin_that_a_lookup_was_spent(
    provider: str,
) -> None:
    """Dua provider ini memakai satu lookup dari kuota harian tiap tes."""
    with respx.mock(assert_all_called=False) as mock:
        mock_ioc(mock, provider).respond(json=IOC_OK_JSON[provider])

        result = await run_probe(provider, ioc_settings(provider))

    assert "8.8.8.8" in result.detail
    assert "kuota" in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", IOC_PROVIDERS)
async def test_ioc_probe_skips_an_empty_key_without_any_request(provider: str) -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock_ioc(mock, provider)

        result = await run_probe(provider, ioc_settings(provider, key=""))

    assert result.status == "SKIP"
    assert "kosong" in result.detail
    assert not route.called


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("provider", IOC_PROVIDERS)
async def test_ioc_probe_fails_when_the_key_is_rejected(provider: str, status: int) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_ioc(mock, provider).respond(status)

        result = await run_probe(provider, ioc_settings(provider))

    assert result.status == "FAIL"
    assert f"ditolak (HTTP {status}) -- key salah/dicabut" in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", IOC_PROVIDERS)
async def test_ioc_probe_treats_rate_limiting_as_a_note_not_a_failure(provider: str) -> None:
    """429 berarti key dikenali tapi kuotanya habis: menolak menyimpan key yang benar karena itu
    akan memaksa operator menunggu jendela kuota."""
    with respx.mock(assert_all_called=False) as mock:
        mock_ioc(mock, provider).respond(429)

        result = await run_probe(provider, ioc_settings(provider))

    assert result.status == "NOTE"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 500, 502])
@pytest.mark.parametrize("provider", IOC_PROVIDERS)
async def test_ioc_probe_fails_with_the_status_code_on_any_other_http_error(
    provider: str, status: int
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_ioc(mock, provider).respond(status)

        result = await run_probe(provider, ioc_settings(provider))

    assert result.status == "FAIL"
    assert f"HTTP {status}" in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError, httpx.ReadTimeout],
    ids=["connect", "timeout"],
)
@pytest.mark.parametrize("provider", IOC_PROVIDERS)
async def test_ioc_probe_network_error_shows_only_the_exception_type(
    provider: str, error: type[httpx.HTTPError]
) -> None:
    boom = error(f"boom {IOC_URL[provider]} {IOC_KEY}")
    with respx.mock(assert_all_called=False) as mock:
        mock_ioc(mock, provider).mock(side_effect=boom)

        result = await run_probe(provider, ioc_settings(provider))

    assert result.status == "FAIL"
    assert error.__name__ in result.detail
    assert IOC_KEY not in result.detail
    assert "boom" not in result.detail
    assert "https://" not in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", LOOKUP_PROVIDERS)
async def test_ioc_probe_fails_with_unknown_response_on_a_payload_of_the_wrong_shape(
    provider: str,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_ioc(mock, provider).respond(json=IOC_BAD_SHAPE_JSON[provider])

        result = await run_probe(provider, ioc_settings(provider))

    assert result.status == "FAIL"
    assert result.detail == "respons tidak dikenal (ValueError)"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", LOOKUP_PROVIDERS)
async def test_ioc_probe_fails_with_unknown_response_on_a_body_that_is_not_json(
    provider: str,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_ioc(mock, provider).respond(200, text="<html>bukan json</html>")

        result = await run_probe(provider, ioc_settings(provider))

    assert result.status == "FAIL"
    assert re.fullmatch(r"respons tidak dikenal \(\w+\)", result.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", IOC_PROVIDERS)
async def test_ioc_probe_never_shows_a_key_that_the_provider_echoes_back(provider: str) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_ioc(mock, provider).respond(401, text=f"invalid key {IOC_KEY}")

        result = await run_probe(provider, ioc_settings(provider))

    assert result.status == "FAIL"
    assert IOC_KEY not in result.detail
