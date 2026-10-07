"""Katalog tech: vendor dan keluarga produk (ROADMAP #19, `docs/CVE_CATALOG_DESIGN.md` 3.2).

Katalog diturunkan dari data CVE (resolver `cti_core.catalog_resolve`) tapi **berumur sendiri**:
mirror CVE dibuang retensi tiap tahun kalender, katalog TIDAK. Produk yang CVE-nya hanya ada di 2025
harus tetap ada di 2027 selama masih dirujuk Monitor (`techstack_targets`). Karena itu:

- statistik `cve_seen_total` hanya naik (satu CVE dihitung SEKALI per vendor dan SEKALI per
  keluarga, saat tautan pertamanya dibuat di `cve_record_products`), tidak turun saat mirror
  dipangkas;
- FK dari `techstack_targets` ke sini `RESTRICT`: baris yang dirujuk tidak bisa terhapus.

Kunci (`key`) adalah bentuk ternormalisasi dari resolver; `display_name` hanya tampilan.
"""

from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base, TimestampMixin

DISPLAY_CPE = "cpe"
DISPLAY_CNA = "cna"
"""Asal `display_name`. Ejaan dari CPE biasanya huruf kecil bergaris-bawah (`palo_alto_networks`);
ejaan CNA (`Palo Alto Networks`) menggantikannya begitu muncul."""

FAMILY_AUTO = "auto"
FAMILY_MANUAL = "manual"
FAMILY_CUSTOM = "custom"
"""`auto` dari ingest, `manual` hasil koreksi/merge admin, `custom` ditambah pengguna (belum
terverifikasi: tidak berasal dari data CVE)."""


class CatalogVendor(TimestampMixin, Base):
    __tablename__ = "catalog_vendors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    """`cti_core.catalog_resolve.vendor_key`; `~none` = "(tanpa vendor)"."""
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    display_source: Mapped[str] = mapped_column(String(3), nullable=False, default=DISPLAY_CNA)
    monitorable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """False untuk "(tanpa vendor)": tidak ada vendor yang bisa dipantau."""
    first_seen: Mapped[datetime.date | None] = mapped_column(Date)
    last_cve_at: Mapped[datetime.date | None] = mapped_column(Date)
    cve_seen_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CatalogFamily(TimestampMixin, Base):
    __tablename__ = "catalog_families"
    __table_args__ = (UniqueConstraint("vendor_id", "key", name="uq_catalog_families_vendor_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_vendors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(400), nullable=False)
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    display_source: Mapped[str] = mapped_column(String(3), nullable=False, default=DISPLAY_CNA)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default=FAMILY_AUTO)
    first_seen: Mapped[datetime.date | None] = mapped_column(Date)
    last_cve_at: Mapped[datetime.date | None] = mapped_column(Date)
    cve_seen_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CatalogFamilyAlias(TimestampMixin, Base):
    """`alias_key` (vendor + produk kompak, `catalog_resolve.alias_key`) -> keluarga. Dicek resolver
    SEBELUM lipat otomatis, jadi koreksi manual bertahan lintas ingest."""

    __tablename__ = "catalog_family_aliases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alias_key: Mapped[str] = mapped_column(String(800), nullable=False, unique=True)
    family_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(200))
