"""`classify_tweet`: prompt pendek khusus tweet, task `classify_tweet`, tag `tweet`."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from cti_enrich import tweet_prompt_eval
from cti_enrich.stages import classify as classify_mod
from cti_enrich.stages.classify import _TWEET_PROMPT, TWEET_PROMPT_VERSION, ClassifyResult

REPLY = json.dumps({"related_cyber": True, "confidence": 0.9, "confirmed_incident": True})


class FakeClient:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        content = self.replies[min(len(self.requests), len(self.replies)) - 1]
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


def _use(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> tuple[FakeClient, list[str]]:
    client = FakeClient(replies)
    tasks: list[str] = []

    def _get(**kw: Any) -> tuple[FakeClient, str]:
        tasks.append(kw["task"])
        return client, "test-model"

    monkeypatch.setattr(classify_mod, "get_llm_client", _get)
    monkeypatch.setattr(classify_mod, "store_param", lambda: {})
    return client, tasks


def test_classify_tweet_uses_the_tweet_prompt_and_task(monkeypatch: pytest.MonkeyPatch) -> None:
    client, tasks = _use(monkeypatch, [REPLY])

    result = classify_mod.classify_tweet("Acme Corp hit by ransomware")

    assert tasks == ["classify_tweet"]
    system = next(m["content"] for m in client.requests[0]["messages"] if m["role"] == "system")
    assert system == _TWEET_PROMPT
    assert result.confirmed_incident is True
    assert result.audit["prompt_version"] == TWEET_PROMPT_VERSION
    assert client.requests[0]["prompt_version"] == TWEET_PROMPT_VERSION


def test_classify_tweet_retry_uses_tweet_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _use(monkeypatch, ["not json", REPLY])

    classify_mod.classify_tweet("x")

    second = next(m["content"] for m in client.requests[1]["messages"] if m["role"] == "user")
    assert second.startswith("<tweet>x</tweet>")


def test_tweet_prompt_is_short() -> None:
    assert len(_TWEET_PROMPT) <= 3200


def test_tweet_prompt_asks_for_every_x_intel_field() -> None:
    for key in (
        "related_cyber",
        "confidence",
        "industries_impacted",
        "victim_countries",
        "actor_countries",
        "confirmed_incident",
        "incident_confidence",
        "incident_indicators",
        "victim_name",
    ):
        assert key in _TWEET_PROMPT


def test_eval_reports_agreement() -> None:
    texts = ["a", "b", "c", "d"]
    old = {"a": True, "b": True, "c": False, "d": False}
    new = {"a": True, "b": True, "c": False, "d": True}

    def _mk(table: dict[str, bool]):
        return lambda t: ClassifyResult(related_cyber=table[t], confirmed_incident=table[t])

    report = tweet_prompt_eval.compare(texts, _mk(old), _mk(new))

    assert report["n"] == 4
    assert report["related_cyber_agreement"] == 0.75
    assert report["confirmed_incident_agreement"] == 0.75
    assert report["old_prompt_chars"] > report["new_prompt_chars"]
