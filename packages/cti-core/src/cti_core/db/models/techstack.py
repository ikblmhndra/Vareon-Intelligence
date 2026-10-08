"""Tech stack organisasi -- gantiin `threatintel.techstack`.

Salah satu dari TIGA pola "web kurasi, scraper patuh" yang udah kebukti
bagus (lihat plan §8.3): web nulis daftar tech stack, `newCveThreat`
(Fase 4) baca buat nentuin keyword pencarian NVD. **Tanpa tabel ini
ke-seed, pipeline CVE gak jalan** -- lihat plan konsekuensi
"Postgres + DB kosong", dan Fase 10.1 (seed data referensi).
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cti_core.db.base import Base, TimestampMixin
from cti_core.db.models.catalog import CatalogFamily, CatalogVendor


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
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    """Dipantau atau tidak (ROADMAP #19). False = disembunyikan, TIDAK dihapus (ticket tidak pernah
    hilang). Entri tanpa target (entri lama/custom) tetap aktif dan tetap dicocokkan lewat teks."""

    targets: Mapped[list[TechStackTarget]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TechStackTarget.id",
    )
    """Sasaran katalog. Kosong = entri lama/custom (dicocokkan lewat teks)."""


class TechStackTarget(Base):
    """Sasaran katalog satu entri Monitor: vendor ATAU keluarga (tepat satu). Satu entri boleh punya
    banyak target (`junos` = tiga keluarga Juniper; `graylog` = dua vendor yang dieja beda). Entri
    TANPA target = entri lama/custom yang dicocokkan lewat teks seperti sebelum katalog ada."""

    __tablename__ = "techstack_targets"
    __table_args__ = (
        CheckConstraint(
            "(vendor_id IS NOT NULL) <> (family_id IS NOT NULL)", name="exactly_one_target"
        ),
        Index(
            "uq_techstack_targets_entry_vendor",
            "entry_id",
            "vendor_id",
            unique=True,
            postgresql_where=text("vendor_id IS NOT NULL"),
        ),
        Index(
            "uq_techstack_targets_entry_family",
            "entry_id",
            "family_id",
            unique=True,
            postgresql_where=text("family_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("techstack_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalog_vendors.id", ondelete="RESTRICT"), index=True
    )
    family_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalog_families.id", ondelete="RESTRICT"), index=True
    )

    vendor: Mapped[CatalogVendor | None] = relationship(lazy="joined")
    family: Mapped[CatalogFamily | None] = relationship(lazy="joined")
