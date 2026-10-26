"""Skor confidence artikel (grading Admiralty sumber + bonus TTP/aktor) dan nilai bawaan grade
sumber per `content_kind` (rilis 0.8.6, spec P2 cheap wins 5.1 dan 5.2).

Fungsi murni, tanpa DB: dipakai persist enrichment (sync, worker) dan `cti_api.services.confidence`
(async, recompute) supaya satu rumus saja. Dipindah dari `cti_api.services.confidence` tanpa
perubahan rumus."""

from __future__ import annotations

from collections.abc import Iterable

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
