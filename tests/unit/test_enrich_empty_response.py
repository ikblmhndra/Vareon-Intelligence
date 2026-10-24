"""Respons 200 tanpa `choices` dari gateway (model `openrouter/free`) = kegagalan TRANSIEN, bukan
`TypeError` yang menghilangkan artikel (prod 2026-10-20/21: 3 artikel, tidak di-retry)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from cti_core.llm.client import EmptyLLMResponse, first_choice
from cti_enrich.stages import classify as classify_mod
from cti_enrich.stages import extract_ttps as ttp_mod


def _client_returning(completion: Any) -> Any:
    def create(**_: Any) -> Any:
        return completion

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.mark.parametrize(
    "completion",
    [
        SimpleNamespace(choices=None),
        SimpleNamespace(choices=[]),
        {"choices": None, "error": {"code": 502}},
    ],
)
def test_first_choice_raises_a_named_error_when_choices_are_missing(completion: Any) -> None:
    with pytest.raises(EmptyLLMResponse):
        first_choice(completion)


def test_first_choice_returns_the_first_choice() -> None:
    assert first_choice(SimpleNamespace(choices=["a", "b"])) == "a"


@pytest.mark.parametrize(
    ("module", "call"),
    [
        (classify_mod, lambda: classify_mod.classify("Some title")),
        (ttp_mod, lambda: ttp_mod.extract_ttps("some summary")),
    ],
)
def test_stages_raise_empty_response_not_typeerror(
    monkeypatch: pytest.MonkeyPatch, module: Any, call: Any
) -> None:
    client = _client_returning(SimpleNamespace(choices=None))
    monkeypatch.setattr(module, "get_llm_client", lambda **_: (client, "test-model"))
    monkeypatch.setattr(module, "store_param", lambda: {})

    with pytest.raises(EmptyLLMResponse):
        call()


def test_the_enrich_task_retries_an_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    # `cti_worker.celery_app` memuat Settings saat diimpor, jadi env minimal dipasang dulu.
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test-secret")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test-session")
    from cti_worker.tasks.enrich import _TRANSIENT_ERRORS

    assert issubclass(EmptyLLMResponse, _TRANSIENT_ERRORS)
