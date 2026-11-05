"""Kebijakan kegagalan task `enrich.article` sesudah P7g: hanya error DB/jaringan yang di-retry
Celery (task ini tidak memanggil LLM lagi), dan kegagalan final dicatat sebagai job `classify`
`failed` lewat `_record_failed_job`. Modul yang diuji: `cti_worker.tasks.enrich`."""

from __future__ import annotations

import json
from typing import Any

import httpx
import openai
import pytest
import sqlalchemy.exc
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
    ("error_class", "retried"),
    [
        (httpx.ConnectError, True),
        (sqlalchemy.exc.OperationalError, True),
        (sqlalchemy.exc.InterfaceError, True),
        (openai.APITimeoutError, False),
        (openai.InternalServerError, False),
        (openai.RateLimitError, False),
        (EmptyLLMResponse, False),
        (json.JSONDecodeError, False),
        (openai.AuthenticationError, False),
        (TypeError, False),
    ],
)
def test_only_db_and_network_errors_are_retried(
    enrich: Any, error_class: type[BaseException], retried: bool
) -> None:
    assert issubclass(error_class, enrich._TRANSIENT_ERRORS) is retried


def _status_error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    request = httpx.Request("POST", "http://gateway/v1/chat/completions")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


def test_unretried_error_is_recorded_as_failed_job(
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
    monkeypatch.setattr(enrich, "_record_failed_job", lambda *a: recorded.append(a))

    kwargs = {"title": "T", "url": "u", "posted_on": None, "source": "S", "scraper_id": None}
    with pytest.raises(openai.BadRequestError) as caught:
        enrich.enrich_article.run(**kwargs)
    assert retried == []  # langsung gagal, tanpa retry Celery

    class Info:
        type = type(caught.value)

    # Tipe ASLI dari `einfo.type`, bukan kelas dasar hasil pickling Celery.
    enrich.enrich_article.on_failure(caught.value, "tid", (), kwargs, Info())
    assert recorded[0][1:] == (caught.value, "BadRequestError")


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
        return types.SimpleNamespace(accepted=True, news_type="x", pending_job_id=None)

    monkeypatch.setattr(pipeline, "run_pipeline", fake_pipeline)
    enrich.enrich_article.run(
        title="T", url="u", posted_on=None, source="S", scraper_id=None, **extra
    )
    assert seen["alert"] is expected
