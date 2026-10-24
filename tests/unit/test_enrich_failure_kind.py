"""`rejected_articles.failure_kind` mengikuti kebijakan retry task `enrich.article`:
kelas yang di-retry = `transient`, JSON rusak = `json`, konfigurasi gateway
(400/401/403/404) = `config`, sisanya (kuota, bug) = `permanent`.
Modul yang diuji: `cti_worker.tasks.enrich._failure_kind`."""

from __future__ import annotations

import json
from typing import Any

import httpx
import openai
import pytest
from cti_core.llm.client import EmptyLLMResponse


@pytest.fixture
def enrich(monkeypatch: pytest.MonkeyPatch) -> Any:
    # `cti_worker.celery_app` memuat Settings saat diimpor, jadi env minimal dipasang dulu.
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test-secret")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test-session")
    from cti_worker.tasks import enrich as module

    return module


@pytest.mark.parametrize(
    ("error_class", "kind"),
    [
        (openai.APITimeoutError, "transient"),
        (openai.InternalServerError, "transient"),
        (openai.RateLimitError, "transient"),
        (httpx.ConnectError, "transient"),
        (EmptyLLMResponse, "transient"),
        (json.JSONDecodeError, "json"),
        (openai.AuthenticationError, "config"),
        (openai.BadRequestError, "config"),
        (openai.PermissionDeniedError, "config"),
        (openai.NotFoundError, "config"),
        (TypeError, "permanent"),
    ],
)
def test_failure_kind_follows_the_retry_policy(
    enrich: Any, error_class: type[BaseException], kind: str
) -> None:
    assert enrich._failure_kind(error_class) == kind


def _status_error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    request = httpx.Request("POST", "http://gateway/v1/chat/completions")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


def test_config_error_is_not_retried_and_is_recorded_as_config(
    enrich: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import contextlib

    import cti_core.db.engine as engine
    import cti_enrich.pipeline as pipeline

    monkeypatch.setattr(engine, "sync_session", lambda: contextlib.nullcontext(object()))

    def boom(**_k: object) -> None:
        raise _status_error(openai.BadRequestError, 400)

    monkeypatch.setattr(pipeline, "run_pipeline", boom)
    retried: list[object] = []
    monkeypatch.setattr(enrich.enrich_article, "retry", lambda **k: retried.append(k))
    recorded: list[tuple[Any, ...]] = []
    monkeypatch.setattr(enrich, "_record_enrichment_failure", lambda *a: recorded.append(a))

    kwargs = {"title": "T", "url": "u", "posted_on": None, "source": "S", "scraper_id": None}
    with pytest.raises(openai.BadRequestError) as caught:
        enrich.enrich_article.run(**kwargs)
    assert retried == []  # langsung gagal, tanpa retry Celery

    class Info:
        type = type(caught.value)

    enrich.enrich_article.on_failure(caught.value, "tid", (), kwargs, Info())
    assert recorded[0][1:] == (caught.value, "BadRequestError", "config")


@pytest.mark.parametrize(
    ("extra", "expected"),
    [({"replay": True, "alert": True}, True), ({"replay": True}, False), ({}, True)],
)
def test_alert_override_beats_replay_default(
    enrich: Any, monkeypatch: pytest.MonkeyPatch, extra: dict[str, bool], expected: bool
) -> None:
    import contextlib
    import types

    import cti_core.db.engine as engine
    import cti_enrich.pipeline as pipeline

    monkeypatch.setattr(engine, "sync_session", lambda: contextlib.nullcontext(object()))
    seen: dict[str, Any] = {}

    def fake_pipeline(**k: Any) -> Any:
        seen.update(k)
        return types.SimpleNamespace(accepted=True, news_type="x")

    monkeypatch.setattr(pipeline, "run_pipeline", fake_pipeline)
    enrich.enrich_article.run(
        title="T", url="u", posted_on=None, source="S", scraper_id=None, **extra
    )
    assert seen["alert"] is expected
