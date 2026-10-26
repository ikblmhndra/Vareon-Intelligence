"""Skor artikel: grading Admiralty (reliabilitas sumber + kredibilitas terhitung), confidence, dan
prioritas, plus nilai bawaan grade sumber per `content_kind` (rilis 0.8.6, spec P2).

P6: kredibilitas tidak lagi dibaca dari kolom per-sumber; ia dihitung per artikel lewat tangga
aturan (korroborasi story, artefak CVE/IOC/TTP eksplisit, jenis sumber primer) supaya benar-benar
membedakan artikel. `assess()` fungsi murni tanpa DB: dipakai persist enrichment (sync, worker)
dan recompute API (async) supaya satu rumus saja. Bobot sengaja jadi konstanta modul agar bisa
dituning di satu tempat. `compute_score` lama masih ada sampai pemanggilnya dipindah."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

DEFAULT_GRADES: dict[str, tuple[str, str]] = {
    "kev": ("A", "1"),
    "advisory": ("A", "2"),
    "exploit": ("B", "2"),
    "vendor_research": ("B", "2"),
    "news": ("C", "3"),
    "vendor_marketing": ("C", "4"),
    "social": ("D", "4"),
}
"""`content_kind` -> `(reliability_grade, credibility_code)` untuk baris `origin='default'`."""

BONUS_TTP_SOURCES = frozenset({"explicit", "llm"})
"""Sumber TTP yang dapat bonus confidence (P4): TTP `keyword` Tier 1 belum diukur presisinya."""


def bonus_ttp_count(sources: Iterable[str]) -> int:
    """Jumlah TTP yang dihitung untuk bonus confidence, dari kolom `source` tiap TTP. Satu
    aturan untuk persist enrichment dan recompute API, supaya skor tidak beda antar jalur."""
    return sum(1 for s in sources if s in BONUS_TTP_SOURCES)


_RELIABILITY_SCORE = {"A": 100, "B": 80, "C": 60, "D": 40, "E": 20, "F": 50}
_CREDIBILITY_SCORE = {"1": 100, "2": 80, "3": 60, "4": 40, "5": 20, "6": 50}


def _reliability_to_score(grade: str) -> int:
    return _RELIABILITY_SCORE.get(grade.upper(), 50)


def _credibility_to_score(code: str) -> int:
    return _CREDIBILITY_SCORE.get(str(code), 50)


def compute_score(
    reliability_grade: str | None,
    credibility_code: str | None,
    ttp_count: int,
    ta_count: int,
) -> int:
    rel = _reliability_to_score(reliability_grade) if reliability_grade else 50
    cred = _credibility_to_score(credibility_code) if credibility_code else 50
    base = (rel + cred) / 2
    ttp_bonus = min(ttp_count * 5, 20)
    ta_bonus = min(ta_count * 10, 10)
    return min(100, max(0, round(base + ttp_bonus + ta_bonus)))


PRIMARY_KINDS = frozenset({"kev", "advisory", "vendor_research", "exploit"})
"""`content_kind` sumber primer; `news`, `vendor_marketing`, `social`, dan tak dikenal bukan."""

CONFIDENCE_SCALE_RELIABILITY = {"A": 90, "B": 70, "C": 50, "D": 30, "E": 10, "F": 50}
CONFIDENCE_SCALE_CREDIBILITY = {1: 90, 2: 70, 3: 50, 4: 30, 5: 10, 6: 50}
"""Skala Admiralty-ke-confidence STIX 2.1 untuk kedua separuh; F/6 netral (50)."""

PRIORITY_CONFIRMED_INCIDENT = 25
PRIORITY_KEV = 15
PRIORITY_POC = 8
PRIORITY_PER_TTP = 3
PRIORITY_TTP_MAX = 12
PRIORITY_ACTOR = 8
PRIORITY_PER_EXTRA_SOURCE = 4
PRIORITY_CORROBORATION_MAX = 16


@dataclass(frozen=True, slots=True)
class ArticleFacts:
    """Fakta mentah satu artikel; dikumpulkan loader (DB) lalu diberikan ke `assess`."""

    reliability_grade: str | None
    content_kind: str | None
    story_source_count: int
    has_cve: bool
    has_ioc: bool
    explicit_ttp_count: int
    bonus_ttp_count: int
    has_actor: bool
    confirmed_incident: bool
    kev: bool
    poc: bool
    credibility_override: int | None = None
    confidence_override: int | None = None


@dataclass(frozen=True, slots=True)
class Assessment:
    reliability_grade: str
    credibility: int
    confidence_score: int
    priority_score: int
    reasons: dict[str, Any]

    @property
    def admiralty_code(self) -> str:
        return f"{self.reliability_grade}{self.credibility}"


def _credibility(facts: ArticleFacts) -> tuple[int, list[str]]:
    """Tangga aturan kredibilitas, cocok-pertama menang (spec P6 2.2)."""
    if facts.credibility_override is not None:
        return facts.credibility_override, ["analyst"]
    if facts.reliability_grade is None:
        return 6, ["ungraded"]

    artefacts: list[str] = []
    if facts.has_cve:
        artefacts.append("cve")
    if facts.has_ioc:
        artefacts.append("ioc")
    if facts.explicit_ttp_count > 0:
        artefacts.append("explicit_ttp")
    primary = facts.content_kind in PRIMARY_KINDS
    sources = facts.story_source_count

    if facts.content_kind == "kev":
        return 1, ["official", *artefacts]
    if sources >= 3 and artefacts:
        return 1, ["corroborated_3", *artefacts]
    if artefacts and (sources >= 2 or primary):
        return 2, ["corroborated_2" if sources >= 2 else "primary", *artefacts]
    if primary or artefacts or sources >= 2:
        codes: list[str] = []
        if primary:
            codes.append("primary")
        if sources >= 2:
            codes.append("corroborated_2")
        return 3, [*codes, *artefacts]
    return 4, ["single_aggregator"]


def assess(facts: ArticleFacts) -> Assessment:
    """Hitung reliabilitas, kredibilitas, confidence, dan prioritas satu artikel."""
    grade = (facts.reliability_grade or "F").upper()
    credibility, cred_reasons = _credibility(facts)

    if facts.confidence_override is not None:
        confidence = facts.confidence_override
    else:
        rel = CONFIDENCE_SCALE_RELIABILITY.get(grade, 50)
        cred = CONFIDENCE_SCALE_CREDIBILITY.get(credibility, 50)
        confidence = round((rel + cred) / 2)

    signals: list[tuple[str, int]] = []
    if facts.confirmed_incident:
        signals.append(("confirmed_incident", PRIORITY_CONFIRMED_INCIDENT))
    if facts.kev:
        signals.append(("kev", PRIORITY_KEV))
    elif facts.poc:
        signals.append(("poc", PRIORITY_POC))
    ttps = min(facts.bonus_ttp_count * PRIORITY_PER_TTP, PRIORITY_TTP_MAX)
    if ttps > 0:
        signals.append(("ttps", ttps))
    if facts.has_actor:
        signals.append(("actor", PRIORITY_ACTOR))
    extra = min(
        max(facts.story_source_count - 1, 0) * PRIORITY_PER_EXTRA_SOURCE,
        PRIORITY_CORROBORATION_MAX,
    )
    if extra > 0:
        signals.append(("corroboration", extra))
    signals.sort(key=lambda s: (-s[1], s[0]))

    return Assessment(
        reliability_grade=grade,
        credibility=credibility,
        confidence_score=confidence,
        priority_score=confidence + sum(p for _, p in signals),
        reasons={
            "credibility": cred_reasons,
            "priority": [{"code": c, "points": p} for c, p in signals],
        },
    )
