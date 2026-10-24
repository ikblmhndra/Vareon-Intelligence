"""Prompt TTP, input teks penuh, dan verifikasi evidence (spec 6.1 butir 5)."""

from __future__ import annotations

import pytest
from cti_enrich import pipeline
from cti_enrich.stages import extract_ttps as ttp_mod
from cti_enrich.stages.extract_ttps import Technique, TtpResult, verify_evidence

LDQ, RDQ, LSQ, RSQ, ELL = (chr(c) for c in (0x201C, 0x201D, 0x2018, 0x2019, 0x2026))


def _tech(tid: str, evidence: str) -> Technique:
    return Technique(technique_id=tid, technique_name="n", evidence=evidence)


def test_prompt_allows_none() -> None:
    prompt = ttp_mod._TTP_SYSTEM_PROMPT
    assert "up to 5" in prompt
    assert '"has_techniques" to false' in prompt
    assert "top 5" not in prompt


def test_evidence_must_be_in_text() -> None:
    text = 'The actor sent  phishing\nemails and said "pay now" and it\'s done...'
    result = TtpResult(
        has_techniques=True,
        techniques=[
            _tech("T1", "SENT PHISHING EMAILS"),  # beda case + spasi
            _tech("T2", "never mentioned anywhere"),  # tidak ada di teks
            _tech("T3", f"said {LDQ}pay now{RDQ}"),  # kutip lengkung
            _tech("T4", f"it{RSQ}s done{ELL}"),  # apostrof + elipsis
            _tech("T5", "   "),  # kosong
        ],
    )
    out = verify_evidence(result, text)
    assert [t.technique_id for t in out.techniques] == ["T1", "T3", "T4"]
    assert out.has_techniques is True


def test_all_dropped_means_no_techniques() -> None:
    result = TtpResult(has_techniques=True, techniques=[_tech("T1", "absent")])
    out = verify_evidence(result, "something else")
    assert out.techniques == [] and out.has_techniques is False


def test_pipeline_uses_text_then_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake(s: str) -> TtpResult:
        seen.append(s)
        return TtpResult(has_techniques=False)

    monkeypatch.setattr(pipeline, "extract_ttps", fake)
    long_text = "a" * 7000
    pipeline._extract_ttps_or_empty("u", long_text, "the summary")
    pipeline._extract_ttps_or_empty("u", "", "the summary")
    assert seen == ["a" * pipeline.TTP_TEXT_CAP, "the summary"]
    assert pipeline.TTP_TEXT_CAP == 6000
