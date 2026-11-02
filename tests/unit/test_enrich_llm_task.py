"""Task `enrich.llm` (P7g Task 4) dan pengirimnya `send_enrich_llm`: task hanya membungkus
`cti_enrich.jobs.run_job` (tanpa retry Celery) dengan `relevance_for` milik worker, dan error
gateway LLM = `GATEWAY_ERRORS` (dijadwalkan ulang tanpa batas, bukan retry `enrich.article`)."""

from __future__ import annotations

import json
from typing import Any

import openai
import pytest
from cti_core.llm.client import EmptyLLMResponse
from cti_enrich.stages.classify import OpenAIQuotaExhausted


@pytest.fixture
def enrich(monkeypatch: pytest.MonkeyPatch) -> Any:
    # `cti_worker.celery_app` memuat Settings saat diimpor, jadi env minimal dipasang dulu.
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test-secret")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test-session")
    from cti_worker.tasks import enrich as module

    return module


def test_task_runs_the_job_with_the_worker_relevance_lookup(
    enrich: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cti_enrich import jobs

    seen: list[tuple[int, dict[str, Any]]] = []

    def fake_run_job(job_id: int, **kw: Any) -> str:
        seen.append((job_id, kw))
        return "done"

    monkeypatch.setattr(jobs, "run_job", fake_run_job)

    assert enrich.enrich_llm.run(job_id=7, decision="accept") == "done"
    assert enrich.enrich_llm.run(job_id=8) == "done"

    assert seen[0][0] == 7 and seen[0][1]["decision"] == "accept"
    assert seen[1][0] == 8 and seen[1][1]["decision"] is None
    assert all(kw["relevance_for"] is enrich._relevance_for for _, kw in seen)


def test_task_is_registered_on_the_enrich_queue_without_retries(enrich: Any) -> None:
    task = enrich.enrich_llm
    assert task.name == "enrich.llm"
    assert task.queue == "enrich"
    assert task.max_retries == 0


@pytest.mark.parametrize(
    ("error_class", "gateway"),
    [
        (openai.APIConnectionError, True),
        (openai.APITimeoutError, True),
        (openai.InternalServerError, True),
        (openai.RateLimitError, True),
        (EmptyLLMResponse, True),
        (OpenAIQuotaExhausted, True),
        (openai.BadRequestError, True),
        (openai.AuthenticationError, True),
        (openai.PermissionDeniedError, True),
        (openai.NotFoundError, True),
        (json.JSONDecodeError, False),
        (TypeError, False),
    ],
)
def test_gateway_errors(error_class: type[BaseException], gateway: bool) -> None:
    from cti_enrich.jobs import GATEWAY_ERRORS

    assert issubclass(error_class, GATEWAY_ERRORS) is gateway


class FakeCelery:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_task(self, name: str, kwargs: dict[str, Any], queue: str) -> None:
        self.calls.append({"name": name, "kwargs": kwargs, "queue": queue})


def test_send_enrich_llm_adds_decision_only_when_given(monkeypatch: pytest.MonkeyPatch) -> None:
    from cti_core import celery_client

    fake = FakeCelery()
    monkeypatch.setattr(celery_client, "get_celery_client", lambda: fake)

    celery_client.send_enrich_llm(3)
    celery_client.send_enrich_llm(4, "reject")

    assert fake.calls == [
        {"name": "enrich.llm", "kwargs": {"job_id": 3}, "queue": "enrich"},
        {"name": "enrich.llm", "kwargs": {"job_id": 4, "decision": "reject"}, "queue": "enrich"},
    ]
