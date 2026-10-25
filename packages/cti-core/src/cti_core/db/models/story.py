"""`stories` -- kelompok artikel yang membahas berita yang sama (dedup saat ingest, P3).

Korpus global seperti `articles` (bukan per klien). Anggota sebuah story adalah
`articles WHERE story_id = X`; tidak ada tabel `story_sources` terpisah. Lihat
`docs/superpowers/specs/2026-10-25-p3-story-dedup-design.md` bagian 5.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base, TimestampMixin


class Story(TimestampMixin, Base):
    __tablename__ = "stories"
    __table_args__ = (
        Index("ix_stories_cve_ids", "cve_ids", postgresql_using="gin"),
        Index("ix_stories_last_seen_at", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    """Judul lead (artikel pertama yang membuka story)."""
    lead_source: Mapped[str] = mapped_column(String(200), nullable=False)
    """Sumber lead, supaya story yang belum punya artikel tetap punya satu anggota
    untuk aturan judul lintas-sumber."""
    lead_article_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("articles.id", ondelete="SET NULL", use_alter=True)
    )
    """Terisi saat anggota pertama dipersist."""
    cve_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    """Gabungan CVE kunci semua anggota."""
    classify: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """ClassifyResult lead tanpa `audit`; NULL = belum bisa diwariskan."""
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    article_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    source_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
