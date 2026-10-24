"""Retry JSON di `classify()` / `extract_ttps()` -- bentuk request yang dikuatkan.

Kasus nyata (e2e staging Fase 10): gateway dev njawab persona "Kiro" (prosa,
bukan JSON) untuk judul tertentu. `temperature=0` bikin retry identik cenderung
ngulang jawaban yang sama, jadi percobaan ulang pakai bentuk yang dikuatkan
(`llm_messages.build_messages`) -- yang terukur 6/6 di gateway asli untuk judul
yang tadinya gagal terus. Percobaan PERTAMA harus tetap verbatim.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from cti_enrich.stages import classify as classify_mod
from cti_enrich.stages import extract_ttps as ttp_mod
from cti_enrich.stages.llm_messages import JSON_ONLY_REMINDER, build_messages

KIRO = "I'm Kiro, a development environment assistant, not a threat intelligence analyst."
CLASSIFY_JSON = json.dumps({"related_cyber": False, "confidence": 0.2, "reason": "vendor blog"})
TTP_JSON = json.dumps(
    {
        "has_techniques": True,
        "techniques": [{"technique_name": "Phishing", "technique_id": "T1566"}],
    }
)


class FakeClient:
    """Balikin jawaban sesuai urutan; catat semua request yang masuk."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        content = self.replies[min(len(self.requests), len(self.replies)) - 1]
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


@pytest.fixture
def use_client(monkeypatch: pytest.MonkeyPatch):
    def _use(module: Any, replies: list[str]) -> FakeClient:
        client = FakeClient(replies)
        monkeypatch.setattr(module, "get_llm_client", lambda **_: (client, "test-model"))
        monkeypatch.setattr(module, "store_param", lambda: {})
        return client

    return _use


def user_content(request: dict[str, Any]) -> str:
    return next(m["content"] for m in request["messages"] if m["role"] == "user")


def test_first_attempt_is_verbatim_and_a_good_answer_needs_no_retry(use_client) -> None:
    client = use_client(classify_mod, [CLASSIFY_JSON])

    result = classify_mod.classify("Some article title")

    assert result.related_cyber is False and len(client.requests) == 1
    assert user_content(client.requests[0]) == "Some article title"  # TANPA pembungkus


def test_persona_answer_is_rescued_by_the_hardened_retry(use_client) -> None:
    client = use_client(classify_mod, [KIRO, CLASSIFY_JSON])

    result = classify_mod.classify("EclecticIQ MCP Server: Connect your AI agents")

    assert result.related_cyber is False
    first, second = (user_content(r) for r in client.requests)
    assert first == "EclecticIQ MCP Server: Connect your AI agents"
    assert second.startswith("<article_title>EclecticIQ MCP Server")  # dibungkus tag
    assert second.endswith(JSON_ONLY_REMINDER)  # + pengingat di pesan user YANG SAMA
    # system prompt (logika bisnis) TIDAK berubah di percobaan ulang
    assert client.requests[0]["messages"][0] == client.requests[1]["messages"][0]


def test_persistent_persona_still_raises_after_three_attempts(use_client) -> None:
    client = use_client(classify_mod, [KIRO])

    with pytest.raises(json.JSONDecodeError):
        classify_mod.classify("Some title")

    assert len(client.requests) == 3
    assert user_content(client.requests[0]) == "Some title"
    assert all(user_content(r).startswith("<article_title>") for r in client.requests[1:])


def test_ttp_stage_uses_the_same_policy_with_its_own_tag(use_client) -> None:
    client = use_client(ttp_mod, [KIRO, TTP_JSON])

    result = ttp_mod.extract_ttps("Attackers sent phishing emails.")

    assert result.has_techniques and result.techniques[0].technique_id == "T1566"
    first, second = (user_content(r) for r in client.requests)
    assert first == "Attackers sent phishing emails."
    assert second.startswith("<article_text>Attackers sent phishing emails.</article_text>")


def test_build_messages_shapes() -> None:
    plain = build_messages("SYS", "judul", attempt=0, tag="t")
    hard = build_messages("SYS", "judul", attempt=2, tag="t")

    assert plain == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "judul"}]
    assert hard[0] == plain[0]
    assert hard[1]["content"] == f"<t>judul</t>\n\n{JSON_ONLY_REMINDER}"


def test_classify_keeps_raw_response_of_every_attempt_for_audit(use_client) -> None:
    use_client(classify_mod, [KIRO, CLASSIFY_JSON])

    audit = classify_mod.classify("Some article title").audit

    assert audit["model"] == "test-model"
    assert audit["prompt_version"] == classify_mod.PROMPT_VERSION
    assert [(a["attempt"], a["parsed"], a["finish_reason"]) for a in audit["attempts"]] == [
        (0, False, "stop"),
        (1, True, "stop"),
    ]
    assert audit["attempts"][0]["content"] == KIRO  # persona mentah ikut tersimpan
    assert json.loads(audit["attempts"][1]["content"])["reason"] == "vendor blog"
