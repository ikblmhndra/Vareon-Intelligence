"""Klien LLM terinstrumentasi: tiap `chat.completions.create` menulis satu baris `llm_calls`."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from cti_core.config import LlmSettings
from cti_core.llm import usage
from cti_core.llm.client import get_llm_client
from openai.resources.chat.completions import Completions


def _settings() -> LlmSettings:
    return LlmSettings(provider="openai", api_key="sk-test", model="m-test")


def _ok(choices: list[Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace()] if choices is None else choices,
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3, total_tokens=15),
    )


@pytest.fixture
def records(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    monkeypatch.setattr(usage, "record_call", lambda **f: out.append(f))
    return out


def _patch_create(monkeypatch: pytest.MonkeyPatch, fake: Any) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def _create(self: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return fake(**kwargs)

    monkeypatch.setattr(Completions, "create", _create)
    return seen


def test_ok_call_records_tokens_and_latency(monkeypatch, records) -> None:
    result = _ok()
    seen = _patch_create(monkeypatch, lambda **_: result)
    client, model = get_llm_client(task="classify", settings=_settings())
    got = client.chat.completions.create(model=model, messages=[], prompt_version="abcd1234")
    assert got is result
    assert "prompt_version" not in seen[0]
    (rec,) = records
    assert rec["status"] == "ok"
    assert rec["prompt_tokens"] == 12
    assert rec["completion_tokens"] == 3
    assert rec["task"] == "classify"
    assert rec["model"] == "m-test" == model
    assert rec["prompt_version"] == "abcd1234"
    assert rec["latency_ms"] >= 0


def test_empty_choices_recorded_as_empty(monkeypatch, records) -> None:
    result = _ok(choices=[])
    _patch_create(monkeypatch, lambda **_: result)
    client, model = get_llm_client(task="classify", settings=_settings())
    assert client.chat.completions.create(model=model, messages=[]) is result
    assert records[0]["status"] == "empty"
    assert records[0]["prompt_version"] is None


def test_error_recorded_and_reraised(monkeypatch, records) -> None:
    req = httpx.Request("POST", "http://x")
    exc = openai.BadRequestError("bad", response=httpx.Response(400, request=req), body=None)

    def _boom(**_: Any) -> Any:
        raise exc

    _patch_create(monkeypatch, _boom)
    client, model = get_llm_client(task="ttp", settings=_settings())
    with pytest.raises(openai.BadRequestError) as info:
        client.chat.completions.create(model=model, messages=[])
    assert info.value is exc
    (rec,) = records
    assert rec["status"] == "error"
    assert rec["error_type"] == "BadRequestError"
    assert rec["http_status"] == 400


def test_recording_failure_never_breaks_the_call(monkeypatch) -> None:
    def _raise(**_: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(usage, "record_call", _raise)
    result = _ok()
    _patch_create(monkeypatch, lambda **_: result)
    client, model = get_llm_client(task="classify", settings=_settings())
    assert client.chat.completions.create(model=model, messages=[]) is result


def test_task_is_required() -> None:
    with pytest.raises(TypeError):
        get_llm_client()  # type: ignore[call-arg]


def test_prompt_version_is_8_hex() -> None:
    assert usage.prompt_version("x") == hashlib.sha256(b"x").hexdigest()[:8]
