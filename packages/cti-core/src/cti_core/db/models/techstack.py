"""Tech stack organisasi -- gantiin `threatintel.techstack`.

Salah satu dari TIGA pola "web kurasi, scraper patuh" yang udah kebukti
bagus (lihat plan §8.3): web nulis daftar tech stack, `newCveThreat`
(Fase 4) baca buat nentuin keyword pencarian NVD. **Tanpa tabel ini
ke-seed, pipeline CVE gak jalan** -- lihat plan konsekuensi
"Postgres + DB kosong", dan Fase 10.1 (seed data referensi).
"""

from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base, TimestampMixin


class TechStackEntry(TimestampMixin, Base):
    __tablename__ = "techstack_entries"
    __table_args__ = (UniqueConstraint("name", "client_id", name="uq_techstack_name_client"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True
    )
    exposure: Mapped[str | None] = mapped_column(String(50))
    """internal | internet-facing | dst -- v3.8.x di app lama."""
    hosting_type: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str | None] = mapped_column(String(100))
    added_date: Mapped[datetime.date | None] = mapped_column(Date)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    """Nama lain produk ini ("pan-os" untuk "palo alto", "routeros" untuk "mikrotik") yang
    diperlakukan SAMA dengan `name` oleh `cti_core.tech_match` -- ROADMAP #19 fase 1. Dibaca
    semua pencocok tech (gate `new_cve`, `score.py`, `cve_priority`, `reconcile_cve_tech`).
    `name` tetap label tampilan DAN kunci join (`cve_tracker.tech`, `get_risk_context`), jadi
    kolom ini tidak mengubah identitas entri. Belum ada UI/API untuk mengubahnya (fase 2);
    sementara lewat SQL, lihat `docs/CVE_TECH_MATCHING.md` 7.1. Entri yang dibuat lewat UI
    mulai dengan `[]`."""
