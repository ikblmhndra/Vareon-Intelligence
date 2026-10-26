"""Keputusan gate relevansi (P5, Task 7): fungsi murni, tanpa DB dan tanpa model."""

from __future__ import annotations

import hashlib

import pytest
from cti_core.config import RelevanceSettings
from cti_enrich.relevance.gate import GateDecision, decide, in_audit_sample
from cti_enrich.relevance.model import Probs

NOT_SAMPLED = "ffffffff" + "0" * 56  # 1.0 -> tidak pernah masuk sampel audit
SAMPLED = "00000000" + "0" * 56  # 0.0 -> selalu masuk sampel audit (rate > 0)


def _probs(p: float) -> Probs:
    return Probs(reject=(1 - p) / 2, best_practice=(1 - p) / 2, threat_news=p)


def _cfg(mode: str = "auto") -> RelevanceSettings:
    return RelevanceSettings(mode=mode)


@pytest.mark.parametrize("p", [0.9, 0.5])
def test_shadow_state_always_shadow(p: float) -> None:
    got = decide(_probs(p), url_hash=NOT_SAMPLED, gate_state="shadow", cfg=_cfg())
    assert got == GateDecision("shadow", in_band=p >= 0.85)


def test_gate_in_band_not_sampled_is_gated() -> None:
    got = decide(_probs(0.9), url_hash=NOT_SAMPLED, gate_state="gate", cfg=_cfg())
    assert got == GateDecision("gated", in_band=True)


def test_gate_in_band_sampled_is_audit() -> None:
    got = decide(_probs(0.9), url_hash=SAMPLED, gate_state="gate", cfg=_cfg())
    assert got == GateDecision("audit", in_band=True)


def test_gate_out_of_band_is_llm() -> None:
    got = decide(_probs(0.5), url_hash=NOT_SAMPLED, gate_state="gate", cfg=_cfg())
    assert got == GateDecision("llm", in_band=False)


def test_mode_shadow_overrides_gate_state() -> None:
    got = decide(_probs(0.9), url_hash=NOT_SAMPLED, gate_state="gate", cfg=_cfg("shadow"))
    assert got == GateDecision("shadow", in_band=True)


def test_in_audit_sample_share() -> None:
    hits = sum(
        in_audit_sample(hashlib.sha256(str(i).encode()).hexdigest(), 0.2) for i in range(10_000)
    )
    assert 0.18 <= hits / 10_000 <= 0.22
