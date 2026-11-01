"""PIR (Priority Intelligence Requirement) -- gantiin `threatintel.
pir_requirements` + `pir_notes` (Mongo). Bagian 2 (survei 21 router sisa,
docs/PROGRESS.md) -- domain baru self-contained, CRUD murni lewat web.

`criteria` (JSONB, bukan tabel anak ternormalisasi): enam list string ad
hoc yang analis susun bebas (threat_actors/industries/countries/news_types/
keywords/ttps) buat nge-filter `articles` -- ini "cair" (plan §3: JSONB
buat yang emang cair), beda dari field artikel sendiri yang UDAH
ternormalisasi (`entity_mentions`, lihat `Article.mentions`).
Matching-nya (hitung coverage, list artikel cocok) pakai
`AsyncArticleRepo.list_filtered` yang sudah ada, BUKAN query builder
terpisah -- kode lama justru punya DUA salinan query builder yang sama
persis (`pir_service._build_query` dan
`ScraperNewsWeb/scripts/export_pir_docx.py::_build_article_query`),
duplikasi yang sengaja gak diikutin di sini.

Matching artikel PIR TIDAK di-filter per client_id (port apa adanya --
kode lama juga gak nge-filter `articles` collection by client di
`pir_service`, cuma record PIR-nya sendiri yang client-scoped). Konsisten
sama skema baru: `Article` (models/article.py) memang gak punya kolom
client_id sama sekali.

Alert otomatis "artikel baru cocok PIR aktif" (`check_new_articles_vs_pirs`
lama) SENGAJA belum diport di sini -- itu salah satu dari 5 loop yang
pindah ke Celery beat (Fase 7.8 "PIR alert", lihat docs/PROGRESS.md),
bukan tanggung jawab CRUD router ini."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base, TimestampMixin

_EMPTY_CRITERIA: dict[str, list[str]] = {
    "threat_actors": [],
    "industries": [],
    "countries": [],
    "news_types": [],
    "keywords": [],
    "ttps": [],
}


class PIRRequirement(TimestampMixin, Base):
    __tablename__ = "pir_requirements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="P2")
    """"P1".."P4" -- string, bukan enum. Diurutin lexical ascending
    (`ORDER BY priority`) sama kayak `.sort("priority", 1)` Mongo lama --
    kebetulan tetap bener karena semua nilai sama panjang, prefix "P"."""
    owner: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    criteria: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=lambda: dict(_EMPTY_CRITERIA)
    )
    start_date: Mapped[datetime.date | None] = mapped_column(Date)
    end_date: Mapped[datetime.date | None] = mapped_column(Date)
    """Inclusive -- PIR otomatis "kadaluarsa" (di-skip alert/matching)
    setelah tanggal ini, port apa adanya dari komentar model lama."""
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True
    )


class PIRNote(Base):
    """Catatan analis per (PIR, url artikel) -- gantiin `pir_notes`.
    Upsert by (pir_id, url), sama kayak `update_one(..., upsert=True)`
    lama."""

    __tablename__ = "pir_notes"
    __table_args__ = (UniqueConstraint("pir_id", "url", name="uq_pir_notes_pir_url"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pir_id: Mapped[int] = mapped_column(
        ForeignKey("pir_requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    analyst: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
