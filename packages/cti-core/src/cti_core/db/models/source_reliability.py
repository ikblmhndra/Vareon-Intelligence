"""Admiralty source reliability grading -- gantiin `threatintel.
source_scores` (Mongo, ditulis `source_score_db_service.py`). Bagian 2
(survei 21 router sisa, docs/PROGRESS.md) -- domain baru self-contained,
analis nge-grade nama sumber (bukan per-artikel) pakai skema Admiralty
(reliability A-F, credibility 1-6).

**Beda dari `source_score_service.py` (TIDAK diport di sini, lain
concern):** itu lookup table hardcoded statis (~127 baris dict Python)
yang dipakai router `intelligence.py` (Bagian 5, dashboard aggregator,
belum diport) buat heuristik cepat. Tabel di sini adalah hasil KURASI
MANUAL analis lewat CRUD, sumber kebenaran berbeda, gak saling gantiin.

Gak ada `client_id` -- port apa adanya, kode lama juga global (satu
grading dipakai lintas client, gak ada `effective_client_id` di
`routers/source_reliability.py` lama sama sekali)."""

from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base


class SourceReliabilityEntry(Base):
    __tablename__ = "source_reliability_entries"
    __table_args__ = (CheckConstraint("origin IN ('default', 'analyst')", name="origin"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    """Uniqueness case-insensitive DIPASTIKAN di layer repository
    (`get_by_name_ci` sebelum create), bukan constraint DB -- pola sama
    persis `AsyncTechStackRepo.create`."""
    analyst_name: Mapped[str] = mapped_column(String(100), nullable=False)
    reliability_grade: Mapped[str] = mapped_column(String(1), nullable=False)
    credibility_code: Mapped[str] = mapped_column(String(1), nullable=False)
    admiralty_code: Mapped[str] = mapped_column(String(2), nullable=False)
    """`{reliability_grade}{credibility_code}` -- denormalized, port apa
    adanya (kode lama nyimpen ini juga, bukan dihitung di query)."""
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    added_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    last_updated: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    origin: Mapped[str] = mapped_column(
        String(10), nullable=False, default="analyst", server_default=text("'analyst'")
    )
    """`default` (baris awal dari `content_kind` scraper, dibuat saat API start) atau `analyst`
    (diketik/diedit analis). Edit lewat API mengubah `default` jadi `analyst`."""
    content_kind: Mapped[str | None] = mapped_column(String(20))
    """Jenis konten scraper (`news`, `advisory`, `vendor_research`, ...) untuk model Admiralty
    P6 (spec 3.2). Diisi `ensure_defaults` saat API start untuk SEMUA baris yang namanya cocok
    `meta.source` (default maupun analis); sumber non-scraper tetap NULL (dianggap bukan primer)."""
