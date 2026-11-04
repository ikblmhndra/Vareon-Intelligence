"""Antrean kerja LLM yang tahan banting (P7g, persist-first): `enrich_jobs`.

Baris hanya ada selama kerja LLM-nya belum selesai; begitu selesai baris dihapus (riwayat panggilan
ada di `llm_calls`). Artikel disimpan LEBIH DULU lewat jalur Tier 0/1, jadi gateway LLM yang mati
tidak lagi membuat artikel hilang atau menumpuk di `rejected_articles`.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base

JOB_KINDS = ("classify", "ttp")
JOB_STATES = ("pending", "failed")
LLM_TTP_STATUSES = ("pending", "done", "skipped", "failed")


class EnrichJob(Base):
    __tablename__ = "enrich_jobs"
    __table_args__ = (
        UniqueConstraint("kind", "url_hash", name="uq_enrich_jobs_kind_url_hash"),
        CheckConstraint("kind IN ('classify', 'ttp')", name="kind_valid"),
        CheckConstraint("state IN ('pending', 'failed')", name="state_valid"),
        Index("ix_enrich_jobs_state_kind_next", "state", "kind", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    """sha256(canonicalize_url(url)); unik per `kind` (satu job classify dan satu ttp per URL)."""
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    scraper_id: Mapped[str | None] = mapped_column(String(100))
    posted_on: Mapped[datetime.date | None] = mapped_column(Date)
    article_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("articles.id", ondelete="CASCADE")
    )
    """Terisi untuk `ttp`; job ikut terhapus bersama artikelnya."""
    input_text: Mapped[str | None] = mapped_column(Text)
    """classify: teks hasil fetch supaya pipeline lanjut tanpa fetch kedua; ttp: teks persis yang
    dikirim ke model (untuk cek evidence). NULL = jalankan bagian depan pipeline dulu."""
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    """Tautan story, hasil relevance, `content_kind`, `tlp`, `pap`."""
    state: Mapped[str] = mapped_column(
        String(10), nullable=False, default="pending", server_default="pending"
    )
    """`failed` menunggu analis."""
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    """Percobaan yang gagal di gateway (tanpa batas)."""
    json_failures: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    """Waktu jatuh tempo sekaligus lease dispatcher."""
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
