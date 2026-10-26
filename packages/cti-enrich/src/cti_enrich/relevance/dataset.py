"""Label latih model relevansi dari `articles` dan `rejected_articles` (spec 6).

Modul ini sengaja TIDAK mengimpor sklearn: `to_examples` murni dan `load_examples` cuma
SELECT kolom yang perlu, jadi murah diimpor dari tempat lain.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from cti_core.db.models.article import Article, RejectedArticle
from sqlalchemy import select
from sqlalchemy.orm import Session

from cti_enrich.relevance.model import Example

BEST_PRACTICE = "Security Technology & Best Practices"
FAILED_PREFIX = "[enrichment_failed]"


@dataclass(frozen=True)
class LabelRow:
    title: str
    kind: Literal["article", "rejected"]
    news_type: str | None
    override_news_type: str | None
    audit: dict[str, Any] | None
    reason: str | None
    failure_kind: str | None
    at: datetime


def _normalise(title: str) -> str:
    return " ".join(title.lower().split())


def _label(row: LabelRow) -> str | None:
    """Kelas baris, atau None bila baris harus dikeluarkan."""
    # Keputusan gerbang/Tier 0 dan warisan story bukan putusan LLM: model tidak boleh belajar
    # dari dirinya sendiri.
    if row.audit and ("skipped" in row.audit or "inherited_from_story" in row.audit):
        return None
    if row.kind == "rejected":
        # Dua syarat sekaligus: baris sebelum 0.8.5 belum punya `failure_kind`.
        if row.failure_kind is not None or (row.reason or "").startswith(FAILED_PREFIX):
            return None
        return "reject"
    news_type = row.override_news_type or row.news_type
    return "best_practice" if news_type == BEST_PRACTICE else "threat_news"


def to_examples(rows: Iterable[LabelRow]) -> list[Example]:
    """Terapkan aturan label lalu dedup per judul ternormalisasi (huruf kecil, spasi dirapatkan).

    Bila label bentrok, `at` terbaru menang; kalau `at` sama, baris yang lebih belakang dalam
    urutan iterasi menang. Example memakai judul ASLI baris pemenang.
    """
    best: dict[str, Example] = {}
    for row in rows:
        label = _label(row)
        if label is None:
            continue
        key = _normalise(row.title)
        prev = best.get(key)
        if prev is None or row.at >= prev.at:
            best[key] = Example(title=row.title, label=label, at=row.at)
    return list(best.values())


def load_examples(session: Session) -> list[Example]:
    """Baca kedua tabel (hanya kolom yang perlu, bukan baris ORM penuh) lalu `to_examples`."""
    art_stmt = select(
        Article.title,
        Article.news_type,
        Article.overrides["news_type"].astext,
        Article.raw_enrichment["classify"],
        Article.created_at,
    )
    rej_stmt = select(
        RejectedArticle.title,
        RejectedArticle.raw_enrichment["classify"],
        RejectedArticle.reason,
        RejectedArticle.failure_kind,
        RejectedArticle.rejected_at,
    )
    rows: list[LabelRow] = [
        LabelRow(title, "article", nt, ov, audit, None, None, at)
        for title, nt, ov, audit, at in session.execute(art_stmt)
    ]
    rows.extend(
        LabelRow(title, "rejected", None, None, audit, reason, fk, at)
        for title, audit, reason, fk, at in session.execute(rej_stmt)
    )
    return to_examples(rows)
