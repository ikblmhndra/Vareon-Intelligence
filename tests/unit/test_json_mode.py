"""JSON mode (`response_format=json_object`) hanya untuk panggilan yang balasannya di-parse JSON.

Exec brief dan risk statement CVE membalas prosa/HTML, jadi tidak boleh memakainya. Mode JSON
OpenAI juga menolak request kalau kata "JSON" tidak ada di pesan, jadi tiap prompt dicek."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from cti_api.services import cve_email, exec_brief, newsletter, newsletter_summary, recap

JSON_MODE = {"type": "json_object"}


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        msg = SimpleNamespace(content="{}")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    client = _FakeClient()
    for mod in (recap, newsletter, newsletter_summary, cve_email, exec_brief):
        monkeypatch.setattr(mod, "get_llm_client", lambda task=None: (client, "m"))
    return client


def _json_calls() -> list[tuple[str, Any]]:
    article = {"title": "t", "source": "s"}
    return [
        ("recap_daily", lambda: recap._call_llm("u", task="recap_daily")),
        (
            "recap_weekly",
            lambda: recap._call_llm("u", recap.WEEKLY_SYSTEM_PROMPT, task="recap_weekly"),
        ),
        (
            "newsletter_article",
            lambda: newsletter._llm_summarize_with_body("t", "b", language="en"),
        ),
        (
            "newsletter_metadata",
            lambda: newsletter._llm_summarize_from_metadata(article, language="en"),
        ),
        ("newsletter_summary", lambda: newsletter_summary._call_llm("u")),
        ("cve_email_validate", lambda: cve_email._llm_cve_validator({"cve_id": "CVE-1"})),
        ("cve_email_mitigation", lambda: cve_email._dedup_mitigation(["a"])),
    ]


@pytest.mark.parametrize("name,call", _json_calls(), ids=lambda v: v if isinstance(v, str) else "")
def test_json_mode_on_json_tasks(fake: _FakeClient, name: str, call: Any) -> None:
    call()
    kwargs = fake.calls[-1]
    assert kwargs["response_format"] == JSON_MODE
    system = kwargs["messages"][0]["content"]
    all_text = " ".join(m["content"] for m in kwargs["messages"])
    assert "json" in all_text.lower(), f"{name}: prompt harus menyebut JSON"
    assert system


def test_no_json_mode_on_prose_tasks(fake: _FakeClient) -> None:
    exec_brief._call_llm("u")
    cve_email._dedup_risk_context("risk")
    assert len(fake.calls) == 2
    assert all("response_format" not in c for c in fake.calls)
