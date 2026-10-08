"""Mirror CVE (ROADMAP #19, `docs/CVE_CATALOG_DESIGN.md` 3.1): CVE terbit >= 2025 dari CVE List V5.

**Dibuang retensi** (tahun kalender: simpan tahun berjalan dan sebelumnya;
`CveMirrorRepo.purge_before`). Dan sengaja TIDAK berhubungan dengan `cve_tracker`: baris tracker
adalah SALINAN yang dibuat saat promosi, tanpa FK ke sini, supaya ticket/ACK/export/dashboard tidak
ikut terhapus retensi.

Hanya yang dibutuhkan untuk menyalin ke `cve_tracker` (padanan `CveItem`) dan untuk mencocokkan
produk; JSON mentah TIDAK disimpan. `affected_lines` memakai format teks yang sama dengan yang kini
ditulis `new_cve` ke `cve_affected` (mis. `Zabbix: < 7.0`); versi terdampak tidak disimpan
terstruktur (keputusan user: ikut yang sudah ada).
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cti_core.db.base import Base, TimestampMixin


class CveRecord(TimestampMixin, Base):
    __tablename__ = "cve_records"

    cve_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    published_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    """Dasar retensi (tanggal terbit, bukan tanggal ubah)."""
    published_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    modified_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    """`cveMetadata.dateUpdated`; upsert menolak record yang LEBIH LAMA dari yang tersimpan."""
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    link: Mapped[str | None] = mapped_column(Text)
    solutions: Mapped[str | None] = mapped_column(Text)
    cvss_score: Mapped[float | None] = mapped_column(Float)
    cvss_severity: Mapped[str | None] = mapped_column(String(20))
    cvss_vector: Mapped[str | None] = mapped_column(Text)
    reference_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    affected_lines: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    has_identity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Ada >= 1 produk yang lolos resolver. False = CVE tanpa identitas (6,2% di data nyata):
    hanya terjangkau lewat teks; ditandai agar jalur teks tidak perlu menghitung ulang."""

    products: Mapped[list[CveRecordProduct]] = relationship(
        back_populates="record", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin"
    )


class CveRecordProduct(Base):
    """Tautan satu CVE ke satu keluarga katalog (satu baris per CVE per keluarga)."""

    __tablename__ = "cve_record_products"
    __table_args__ = (
        UniqueConstraint("cve_id", "family_id", name="uq_cve_record_products_cve_family"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cve_id: Mapped[str] = mapped_column(
        ForeignKey("cve_records.cve_id", ondelete="CASCADE"), nullable=False
    )
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_vendors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    family_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_families.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vendor_raw: Mapped[str] = mapped_column(Text, nullable=False, default="")
    product_raw: Mapped[str] = mapped_column(Text, nullable=False, default="")
    product_norm: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """Produk sebelum dilipat; supaya pemetaan bisa dihitung ulang selama masih dalam retensi."""
    source: Mapped[str] = mapped_column(String(3), nullable=False, default="cna")
    """`cpe` atau `cna` (asal identitas)."""

    record: Mapped[CveRecord] = relationship(back_populates="products")


class CvePromotionShadow(Base):
    """Hasil promosi MODE BAYANGAN (`cve_mirror.promote="shadow"`, ROADMAP #19 irisan 4): untuk
    (CVE, client) mana pipeline mirror AKAN membuat baris `cve_tracker`, dengan tech dan entri
    mana, TANPA menulis ke `cve_tracker`. Dibandingkan dengan tracker hasil `new_cve` oleh
    `tools/ops/compare_promotion_shadow.py` sebelum cutover (`docs/CVE_CATALOG_DESIGN.md` 8.4).

    Satu baris per (CVE, client) seperti tracker. Dibuang bersama mirror oleh retensi
    (`published_date` disalin ke sini karena tak ada FK ke `cve_records`)."""

    __tablename__ = "cve_promotion_shadow"
    __table_args__ = (Index("ix_cve_promotion_shadow_published_date", "published_date"),)

    cve_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), primary_key=True, index=True
    )
    tech: Mapped[str] = mapped_column(String(200), nullable=False)
    """Nama entri techstack yang menang (`techstack_entries.name`), nilai yang akan jadi
    `cve_tracker.tech`."""
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("techstack_entries.id", ondelete="CASCADE"), nullable=False
    )
    specificity: Mapped[str] = mapped_column(String(10), nullable=False)
    """`family` | `vendor` | `text` (`cti_core.cve_promotion`)."""
    published_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    evaluated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
