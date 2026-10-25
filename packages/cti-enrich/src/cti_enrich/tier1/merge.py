"""Gabung hasil Tier 1 (deterministik) dengan keluaran LLM.

Prioritas teknik per ID: explicit > llm > keyword. ID tertulis di teks adalah
fakta, jadi mengalahkan tebakan LLM; keyword cuma heuristik, jadi kalah dari
LLM. Industri: hasil LLM dipertahankan kecuali kosong/"General" DAN Tier 1
menemukan sesuatu (jangan ganti "General" dengan kosong).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from cti_core.attack_ttp import NormalizedTTP

from cti_enrich.stages.classify import resolve_industries
from cti_enrich.stages.extract_ttps import TtpResult
from cti_enrich.tier1.ttps import SourcedTechnique


def merge_ttps(llm: TtpResult | None, tier1: Sequence[SourcedTechnique]) -> list[NormalizedTTP]:
    explicit = {t.ttp_id: t for t in tier1 if t.source == "explicit"}
    winners: dict[str, NormalizedTTP] = {}
    for t in llm.techniques if llm is not None else []:
        if t.technique_id in winners:
            continue
        if t.technique_id in explicit:
            e = explicit[t.technique_id]
            winners[e.ttp_id] = NormalizedTTP(
                e.ttp_id, e.ttp_name, source="explicit", evidence=e.evidence
            )
        else:
            winners[t.technique_id] = NormalizedTTP(
                t.technique_id,
                t.technique_name,
                t.extracted_id,
                t.extracted_name,
                source="llm",
                evidence=t.evidence or None,
            )
    for t in tier1:
        if t.ttp_id not in winners:
            winners[t.ttp_id] = NormalizedTTP(
                t.ttp_id, t.ttp_name, source=t.source, evidence=t.evidence
            )
    return list(winners.values())


def merge_industries(
    llm: list[str], tier1: list[str]
) -> tuple[list[str], Literal["llm", "keyword"]]:
    resolved = resolve_industries(llm)
    if resolved and resolved != ["General"]:
        return resolved, "llm"
    if tier1:
        return tier1, "keyword"
    return resolved, "llm"


def confidence_ttp_count(ttps: Sequence[NormalizedTTP]) -> int:
    """Hanya explicit + llm yang dihitung untuk confidence; keyword tidak."""
    return sum(1 for t in ttps if t.source in {"explicit", "llm"})
