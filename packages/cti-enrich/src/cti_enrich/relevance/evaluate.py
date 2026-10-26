"""Transisi gate relevansi (P5, spec 5): fungsi murni, tanpa sklearn/DB supaya mudah diuji."""

from __future__ import annotations

from typing import Literal

from cti_core.config import RelevanceSettings
from cti_core.db.repositories.relevance import GateStats

GateState = Literal["shadow", "gate"]


def next_state(current: GateState, stats: GateStats, cfg: RelevanceSettings) -> GateState:
    """Status gate berikutnya. `mode != "auto"` memaksa `shadow` (mengembalikan gate yang
    sedang menyala kalau operator menurunkan mode)."""
    if cfg.mode != "auto":
        return "shadow"
    if current == "shadow":
        if stats.band_n >= cfg.gate_min_titles and (
            stats.band_agree / stats.band_n >= cfg.gate_min_agreement
        ):
            return "gate"
        return "shadow"
    audits = stats.audit_last
    if len(audits) >= cfg.revert_samples and (sum(audits) / len(audits) < cfg.revert_min_agreement):
        return "shadow"
    return "gate"
