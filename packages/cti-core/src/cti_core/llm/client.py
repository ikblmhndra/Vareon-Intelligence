"""SATU LLM client OpenAI-compatible -- gantiin 2 fork yang nyaris identik:
`ScraperNews/modules/llm_client.py` dan `ScraperNewsWeb/app/services/llm_client.py`
(33 baris, beda PERSIS satu hal: versi web bikin `OpenAI(**kwargs)` polos, TANPA
`timeout`/`max_retries` -- bisa nge-hang selamanya karena jalan di dalam event loop
FastAPI. Versi module lama pasang `timeout=60.0, max_retries=2`. Port ini pertahanin
proteksi itu (sekarang dari `LlmSettings`, bukan hardcode).

Beda dari KEDUA fork lama: `base_url` custom (`LlmSettings.url`) didukung buat
provider apa pun, bukan cuma 3 URL tetap (openai/deepseek/gemini) -- ini yang
dipakai dev nunjuk ke gateway lokal (9router) yang OpenAI-compatible tapi bukan
openai.com asli. `store_param()` juga jadi off begitu `url` custom di-set, karena
gateway pihak ketiga gak jamin dukung param `store` OpenAI (lihat catatan di bawah).

**Pindah dari `cti_enrich.llm` ke `cti_core.llm` (Fase 7.5, "buang duplikasi")** --
modul ini dari awal ZERO dependency internal `cti_enrich` (cuma `cti_core.config` +
`openai` + stdlib), jadi mekanis murni buat dipindah, sama presedan kayak
`cti_core.ioc.extractor` (Fase 7.3 Bagian 4). Alasan mindahnya: `apps/api` punya
exit criteria "gak ada import `cti_scraper`/`cti_enrich` dari API", jadi 5 service
(`ta_profile`/`exec_brief`/`cve_email`/`newsletter`/`recap`) yang butuh
`get_llm_client()` dulu numpang duplikat SEMPIT sendiri
(`cti_api.services.llm_client.py`, ~15 baris, gak punya `store_param`/
`parse_json_response`). Sekarang `apps/api` DAN `cti_enrich` (`stages/classify.py`,
`stages/extract_ttps.py`) sama-sama import modul ini LANGSUNG dari `cti_core` --
duplikat sempit itu dihapus total, gak ada lagi 2 salinan `get_llm_client()`.

**`parse_json_response()` sekalian nutup 5 titik copas terpisah di `apps/api`**
(`cve_email.py` x2, `newsletter.py` x2, `ta_profile.py` x1) yang semuanya cuma
`json.loads(content or "{}")` POLOS -- gak nahan `<think>...</think>` preamble
atau code-fence markdown kayak fungsi ini, padahal edge case itu UDAH KEBUKTIAN
kejadian beneran lawan dev gateway (lihat docstring `parse_json_response` di
bawah). Bukan cuma dedup kosmetik -- 5 titik itu tadinya rawan `JSONDecodeError`
kalau gateway kebetulan mbalikin salah satu bentuk itu, sekarang kepasang proteksi
yang sama kayak `cti_enrich`'s pipeline udah pake dari awal."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from openai import OpenAI

from cti_core.config import LlmSettings
from cti_core.llm import usage
from cti_core.runtime_secrets.overlay import effective_settings

logger = logging.getLogger(__name__)

_RE_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_RE_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

_DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "deepseek": "deepseek-chat",
    "gemini": "gemini-2.0-flash",
}
_DEFAULT_BASE_URLS = {
    "openai": None,
    "deepseek": "https://api.deepseek.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}


def get_llm_client(*, task: str, settings: LlmSettings | None = None) -> tuple[OpenAI, str]:
    """Return (OpenAI-compatible client, resolved model name).

    `task` wajib: tiap `chat.completions.create` di client ini menulis satu baris `llm_calls`
    (best-effort, lihat `cti_core.llm.usage`). `create` juga menerima `prompt_version=` opsional
    yang dibuang sebelum sampai ke SDK."""
    settings = settings or effective_settings().llm
    provider = settings.provider.lower()
    if provider not in _DEFAULT_MODELS:
        raise ValueError(f"Unknown LLM provider '{provider}'. Valid: {list(_DEFAULT_MODELS)}")

    base_url = settings.url or _DEFAULT_BASE_URLS[provider]
    kwargs: dict[str, Any] = {
        "api_key": settings.api_key,
        "timeout": settings.timeout_s,
        "max_retries": settings.max_retries,
    }
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    model = settings.model or _DEFAULT_MODELS[provider]
    _instrument(client, task=task, model=model)
    return client, model


def _instrument(client: OpenAI, *, task: str, model: str) -> None:
    """Bungkus `client.chat.completions.create` di instance ini (bukan di kelas SDK)."""
    original = client.chat.completions.create

    def create(*args: Any, prompt_version: str | None = None, **kw: Any) -> Any:
        started = time.monotonic()

        def record(**extra: Any) -> None:
            try:
                usage.record_call(
                    task=task,
                    model=model,
                    prompt_version=prompt_version,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    **extra,
                )
            except Exception:
                logger.warning("llm_call_record_failed", exc_info=True)

        try:
            result = original(*args, **kw)
        except Exception as exc:
            record(
                status="error",
                error_type=type(exc).__name__,
                http_status=getattr(exc, "status_code", None),
                prompt_tokens=None,
                completion_tokens=None,
            )
            raise
        tokens = usage_from(result)
        # "Kosong" = definisi `first_choice`: tidak ada `choices`.
        record(
            status="ok" if _field(result, "choices") else "empty",
            error_type=None,
            http_status=None,
            prompt_tokens=tokens.get("prompt_tokens"),
            completion_tokens=tokens.get("completion_tokens"),
        )
        return result

    client.chat.completions.create = create  # type: ignore[method-assign]


def store_param(settings: LlmSettings | None = None) -> dict[str, Any]:
    """`{'store': True}` cuma buat OpenAI ASLI (provider openai TANPA `url`
    custom) -- provider lain, dan gateway custom kayak 9router, gak jamin
    dukung param ini walau ngaku provider="openai"."""
    settings = settings or effective_settings().llm
    if settings.provider.lower() == "openai" and not settings.url:
        return {"store": True}
    return {}


class EmptyLLMResponse(Exception):
    """Gateway membalas 200 tapi `choices` kosong/None (model `openrouter/free` begitu saat
    provider upstream gagal; prod 2026-10-20/21: `TypeError 'NoneType' object is not
    subscriptable`, 3 artikel hilang karena tidak di-retry). Transien: `enrich.article`
    me-retry-nya."""


def first_choice(completion: Any) -> Any:
    """`completion.choices[0]`, atau `EmptyLLMResponse` (bukan TypeError) kalau kosong."""
    choices = _field(completion, "choices")
    if not choices:
        raise EmptyLLMResponse(
            f"LLM membalas tanpa choices: {str(_field(completion, 'error'))[:200]}"
        )
    return choices[0]


_USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _field(obj: Any, name: str) -> Any:
    """`obj.name`, atau `obj[name]` kalau `obj` dict; `None` kalau tidak ada. Objek SDK dan dict
    polos sama-sama muncul dari gateway, dan satu cara baca cukup buat dua-duanya."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def usage_from(completion: Any) -> dict[str, int]:
    """Pemakaian token dari hasil `chat.completions.create()`: `prompt_tokens`,
    `completion_tokens`, `total_tokens`, hanya field yang ada dan berupa bilangan bulat.

    TIDAK PERNAH raise dan tidak mengarang angka. Gateway dev kadang membuang `usage` sama sekali
    atau mengisinya sebagian (field hilang / `null`); hasilnya `{}` atau field yang ada saja.
    Pencatatan biaya jalan SETELAH token-nya terbayar, jadi tidak boleh sampai menggagalkan
    pemanggilnya. Yang butuh ukuran pasti walau gateway diam harus punya ukuran sendiri
    (`wall_ms`, `input_chars` di `recap.generate_daily_recap`)."""
    usage = _field(completion, "usage")
    found: dict[str, int] = {}
    for name in _USAGE_FIELDS:
        value = _field(usage, name)
        if isinstance(value, int):
            found[name] = value
    return found


def parse_json_response(content: str | dict[str, Any] | None) -> dict[str, Any]:
    """Parse a chat completion's content as JSON, tolerating things raw
    `json.loads()` chokes on: a `<think>...</think>` reasoning preamble
    (some reasoning models emit this even with `response_format=json_object`
    -- confirmed live against the dev gateway in `.env`), a ```json
    markdown fence, and an empty/`None` content (the gateway occasionally
    hands back a blank message -- confirmed live during Fase 5's corpus
    test). Replaces the old `.replace("json","")` hack in
    `articleValidator.py:141-146` -- that string-replace corrupted any
    response whose JSON *content* happened to contain the literal substring
    "json" (e.g. a title mentioning "JSON Web Token"); this strips only the
    known wrapper shapes, never touches the payload itself.

    `content` is typed to also accept a plain `dict` -- confirmed live: the
    dev gateway, in `response_format=json_object` mode, occasionally hands
    back an ALREADY-PARSED object instead of a JSON string (a proxy-side
    convenience, not part of the OpenAI response spec). Passed through as-is
    rather than fed to the regex/`json.loads` path below, which expects a
    string and would raise a confusing `TypeError` otherwise."""
    if isinstance(content, dict):
        return content
    if not content:
        raise json.JSONDecodeError("empty response content from LLM", "", 0)
    text = _RE_THINK_BLOCK.sub("", content).strip()
    text = _RE_CODE_FENCE.sub("", text).strip()
    try:
        data: dict[str, Any] = json.loads(text)
        return data
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise
        data = json.loads(text[start : end + 1])
        return data
