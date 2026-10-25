"""Resolver story murni (spec 3.2): tanpa DB, jadi bisa dites dan di-replay.

Urutan aturan, yang pertama cocok menang: CVE, judul persis, judul mirip. Tie-break akhir
selalu id story terkecil karena `StoryRepo.candidates()` tidak mengurutkan hasilnya.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from cti_core.config import StorySettings
from cti_core.db.repositories.story import StoryCandidate

from cti_enrich.story.similarity import title_similarity


def normalize_title(title: str) -> str:
    """Huruf kecil, tanda baca dilipat jadi spasi."""
    return re.sub(r"\W+", " ", title.lower()).strip()


@dataclass(frozen=True)
class ArticleKeys:
    title: str
    source: str
    cve_ids: frozenset[str]
    at: datetime


@dataclass(frozen=True)
class Match:
    story_id: int
    rule: Literal["cve", "title_exact", "title"]


def key_cves(cve_ids: Iterable[str], max_key_cves: int) -> frozenset[str]:
    """CVE kunci artikel; lebih dari `max_key_cves` = roundup, tidak jadi kunci."""
    ids = frozenset(c.upper() for c in cve_ids)
    return ids if len(ids) <= max_key_cves else frozenset()


def resolve(
    keys: ArticleKeys, candidates: list[StoryCandidate], cfg: StorySettings
) -> Match | None:
    """Story tempat artikel bergabung, atau `None` (artikel membuka story baru)."""
    recent = keys.at - timedelta(hours=cfg.window_hours)
    oldest = keys.at - timedelta(days=cfg.max_age_days)
    pool = [c for c in candidates if c.last_seen_at >= recent and c.first_seen_at >= oldest]
    if not pool:
        return None

    key = key_cves(keys.cve_ids, cfg.max_key_cves)

    # Aturan CVE: overlap terbesar, lalu last_seen_at terbaru, lalu id terkecil.
    if key:
        best: tuple[int, datetime, int] | None = None
        best_id = 0
        for c in pool:
            overlap = len(key & c.cve_ids)
            if overlap / len(key) < cfg.cve_overlap or overlap == 0:
                continue
            rank = (overlap, c.last_seen_at, -c.id)
            if best is None or rank > best:
                best, best_id = rank, c.id
        if best is not None:
            return Match(best_id, "cve")

    # Veto CVE untuk aturan judul: artikel punya CVE kunci, story punya CVE, tak ada irisan.
    eligible = [c for c in pool if not (key and c.cve_ids and not (key & c.cve_ids))]
    if not eligible:
        return None

    norm = normalize_title(keys.title)
    exact = [c.id for c in eligible if any(normalize_title(m.title) == norm for m in c.members)]
    if exact:
        return Match(min(exact), "title_exact")

    flat = [(c.id, m.source, m.title) for c in eligible for m in c.members]
    scores = title_similarity(keys.title, [t for _, _, t in flat])
    best_story: int | None = None
    best_score = 0.0
    for (story_id, source, _), score in zip(flat, scores, strict=True):
        if source == keys.source or score < cfg.title_similarity:
            continue
        if (
            best_story is None
            or score > best_score
            or (score == best_score and story_id < best_story)
        ):
            best_story, best_score = story_id, score
    return Match(best_story, "title") if best_story is not None else None
