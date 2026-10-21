"""`rejected_articles.failure_kind` mengikuti kebijakan retry task `enrich.article`:
kelas yang di-retry = `transient`, JSON rusak = `json`, sisanya (401, 400, kuota, bug) =
`permanent`. Modul yang diuji: `cti_worker.tasks.enrich._failure_kind`."""

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
        (openai.AuthenticationError, "permanent"),
        (openai.BadRequestError, "permanent"),
        (TypeError, "permanent"),
    ],
)
def test_failure_kind_follows_the_retry_policy(
    enrich: Any, error_class: type[BaseException], kind: str
) -> None:
    assert enrich._failure_kind(error_class) == kind
