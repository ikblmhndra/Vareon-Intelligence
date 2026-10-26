"""`next_state` -- fungsi murni transisi gate (tabel spec 5)."""

from __future__ import annotations

import pytest
from cti_core.config import RelevanceSettings
from cti_core.db.repositories.relevance import GateStats
from cti_enrich.relevance.evaluate import next_state

CFG = RelevanceSettings()


def _stats(band_n: int = 0, band_agree: int = 0, audit: list[bool] | None = None) -> GateStats:
    return GateStats(band_n=band_n, band_agree=band_agree, audit_last=audit or [])


@pytest.mark.parametrize(
    ("current", "stats", "expected"),
    [
        ("shadow", _stats(199, 199), "shadow"),
        ("shadow", _stats(200, 190), "gate"),
        ("shadow", _stats(1000, 949), "shadow"),
        ("gate", _stats(audit=[False] * 49), "gate"),
        ("gate", _stats(audit=[True] * 46 + [False] * 4), "gate"),
        ("gate", _stats(audit=[True] * 45 + [False] * 5), "shadow"),
    ],
)
def test_next_state_table(current, stats, expected) -> None:
    assert next_state(current, stats, CFG) == expected


def test_mode_shadow_forces_shadow() -> None:
    cfg = RelevanceSettings(mode="shadow")
    assert next_state("gate", _stats(1000, 1000, [True] * 50), cfg) == "shadow"
