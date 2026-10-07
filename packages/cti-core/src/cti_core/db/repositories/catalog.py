"""Repositori sync untuk katalog tech dan mirror CVE (ROADMAP #19, `docs/CVE_CATALOG_DESIGN.md`).

Dipakai ingest (worker, irisan 3), bukan API (repositori async untuk picker menyusul di irisan 5).
Satu instance `CatalogRepo` = satu unit kerja: ia menyimpan cache kunci -> baris supaya backfill
117 ribu CVE tidak melakukan jutaan query; jangan dipakai lintas rollback.

Aturan yang dijaga di sini (bukan di resolver):
- **Statistik hanya naik**: `cve_seen_total` bertambah SEKALI per CVE per vendor dan per keluarga,
  saat tautan pertamanya dibuat; tidak turun saat mirror dipangkas retensi atau tautan berpindah.
- **Upsert idempoten dan tahan urutan**: record yang LEBIH LAMA (`modified_at`) dari yang tersimpan
  ditolak; mengulang record yang sama tidak menaikkan statistik apa pun.
- **Nama tampilan CNA mengalahkan CPE** (`Palo Alto Networks` menggantikan `palo_alto_networks`).
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cti_core.catalog_resolve import VENDOR_NONE_KEY, Resolved
from cti_core.db.models.catalog import (
    DISPLAY_CNA,
    DISPLAY_CPE,
    FAMILY_AUTO,
    CatalogFamily,
    CatalogFamilyAlias,
    CatalogVendor,
)
from cti_core.db.models.cve_mirror import CveRecord, CveRecordProduct

_VENDOR_KEY_MAX = 300
_VENDOR_DISPLAY_MAX = 300
_FAMILY_KEY_MAX = 400
_FAMILY_DISPLAY_MAX = 500


class CatalogError(ValueError):
    """Pelanggaran aturan katalog (mis. alias yang menyeberang vendor)."""


def retention_cutoff(today: datetime.date) -> datetime.date:
    """Tanggal terbit paling awal yang masih disimpan: 1 Januari tahun SEBELUM tahun berjalan
    (tahun kalender: simpan tahun berjalan dan sebelumnya). Di 2026 = 2025-01-01; mulai
    2027-01-01 = 2026-01-01, jadi CVE terbitan 2025 dibuang."""
    return datetime.date(today.year - 1, 1, 1)


class CatalogRepo:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._vendors: dict[str, CatalogVendor] = {}
        self._families: dict[tuple[int, str], CatalogFamily] = {}

    def reset_cache(self) -> None:
        """Buang cache baris. WAJIB setelah rollback savepoint: objek yang dibuat di dalamnya sudah
        hilang dari DB tapi masih ada di cache dan akan dipakai sebagai FK yang tak berlaku."""
        self._vendors.clear()
        self._families.clear()

    # ── alias ─────────────────────────────────────────────────────────────────────────────────

    def alias_map(self) -> dict[str, str]:
        """`{alias_key: family_key}` untuk `catalog_resolve.resolve(aliases=...)`."""
        rows = self.session.execute(
            select(CatalogFamilyAlias.alias_key, CatalogFamily.key).join(
                CatalogFamily, CatalogFamily.id == CatalogFamilyAlias.family_id
            )
        ).all()
        return {alias: family_key for alias, family_key in rows}

    def add_alias(
        self, alias_key: str, family: CatalogFamily, *, created_by: str | None = None
    ) -> CatalogFamilyAlias:
        """Koreksi manual: produk dengan `alias_key` dipetakan ke `family`. Idempoten bila sudah
        menunjuk keluarga yang sama; menolak alias yang menyeberang vendor (alias berawalan kunci
        vendor, `catalog_resolve.alias_key`) dan alias yang sudah menunjuk keluarga lain."""
        vendor = self.session.get(CatalogVendor, family.vendor_id)
        assert vendor is not None
        if not alias_key.startswith(vendor.key + "|"):
            raise CatalogError(
                f"alias {alias_key!r} bukan milik vendor {vendor.key!r} (keluarga {family.key!r})"
            )
        existing = self.session.execute(
            select(CatalogFamilyAlias).where(CatalogFamilyAlias.alias_key == alias_key)
        ).scalar_one_or_none()
        if existing is not None:
            if existing.family_id != family.id:
                raise CatalogError(f"alias {alias_key!r} sudah menunjuk keluarga lain")
            return existing
        row = CatalogFamilyAlias(alias_key=alias_key, family_id=family.id, created_by=created_by)
        self.session.add(row)
        self.session.flush()
        return row

    # ── vendor dan keluarga ───────────────────────────────────────────────────────────────────

    def vendor_for(self, r: Resolved, published: datetime.date) -> CatalogVendor:
        """Ambil/buat vendor untuk hasil resolver; perbarui tampilan dan tanggal. TIDAK menyentuh
        `cve_seen_total` (itu urusan `CveMirrorRepo.upsert`, per tautan baru)."""
        key = r.vendor_key[:_VENDOR_KEY_MAX]
        vendor = self._vendors.get(key)
        if vendor is None:
            vendor = self.session.execute(
                select(CatalogVendor).where(CatalogVendor.key == key)
            ).scalar_one_or_none()
        if vendor is None:
            vendor = CatalogVendor(
                key=key,
                display_name=r.vendor_display[:_VENDOR_DISPLAY_MAX],
                display_source=DISPLAY_CPE if r.source == "cpe" else DISPLAY_CNA,
                monitorable=r.vendor_key != VENDOR_NONE_KEY,
                first_seen=published,
                last_cve_at=published,
                cve_seen_total=0,
            )
            self.session.add(vendor)
            self.session.flush()
        else:
            _touch(vendor, published)
            if vendor.display_source == DISPLAY_CPE and r.source == "cna":
                vendor.display_name = r.vendor_display[:_VENDOR_DISPLAY_MAX]
                vendor.display_source = DISPLAY_CNA
        self._vendors[key] = vendor
        return vendor

    def family_for(
        self, vendor: CatalogVendor, r: Resolved, published: datetime.date
    ) -> CatalogFamily:
        key = r.family_key[:_FAMILY_KEY_MAX]
        cache_key = (vendor.id, key)
        family = self._families.get(cache_key)
        if family is None:
            family = self.session.execute(
                select(CatalogFamily).where(
                    CatalogFamily.vendor_id == vendor.id, CatalogFamily.key == key
                )
            ).scalar_one_or_none()
        if family is None:
            family = CatalogFamily(
                vendor_id=vendor.id,
                key=key,
                display_name=r.family_display[:_FAMILY_DISPLAY_MAX],
                display_source=DISPLAY_CPE if r.source == "cpe" else DISPLAY_CNA,
                source=FAMILY_AUTO,
                first_seen=published,
                last_cve_at=published,
                cve_seen_total=0,
            )
            self.session.add(family)
            self.session.flush()
        else:
            _touch(family, published)
            if family.display_source == DISPLAY_CPE and r.source == "cna":
                family.display_name = r.family_display[:_FAMILY_DISPLAY_MAX]
                family.display_source = DISPLAY_CNA
        self._families[cache_key] = family
        return family


def _touch(row: CatalogVendor | CatalogFamily, published: datetime.date) -> None:
    if row.first_seen is None or published < row.first_seen:
        row.first_seen = published
    if row.last_cve_at is None or published > row.last_cve_at:
        row.last_cve_at = published


@dataclass(frozen=True)
class MirrorRecord:
    """Padanan `CveItem` untuk mirror: yang dibutuhkan untuk menyalin ke `cve_tracker`."""

    cve_id: str
    published_date: datetime.date
    published_at: datetime.datetime | None = None
    modified_at: datetime.datetime | None = None
    summary: str = ""
    link: str | None = None
    solutions: str | None = None
    cvss_score: float | None = None
    cvss_severity: str | None = None
    cvss_vector: str | None = None
    reference_urls: Sequence[str] = ()
    affected_lines: Sequence[str] = ()


@dataclass(frozen=True)
class UpsertResult:
    created: bool
    """True bila baris `cve_records` baru dibuat (bukan pembaruan)."""
    skipped_stale: bool
    """True bila record lebih lama dari yang tersimpan dan ditolak."""
    new_links: int
    """Tautan keluarga yang baru dibuat (= kenaikan statistik katalog)."""
    family_ids: tuple[int, ...]
    """Keluarga yang tertaut ke CVE ini SESUDAH upsert (bahan pencocokan di irisan 4)."""


class CveMirrorRepo:
    def __init__(self, session: Session, catalog: CatalogRepo | None = None) -> None:
        self.session = session
        self.catalog = catalog or CatalogRepo(session)

    def get(self, cve_id: str) -> CveRecord | None:
        return self.session.get(CveRecord, cve_id)

    def upsert(self, record: MirrorRecord, resolved: Sequence[Resolved]) -> UpsertResult:
        """Simpan/perbarui satu CVE beserta tautan keluarganya. `resolved` dari
        `catalog_resolve.resolve_all` (sudah unik per (vendor, keluarga))."""
        existing = self.session.get(CveRecord, record.cve_id)
        if (
            existing is not None
            and existing.modified_at is not None
            and record.modified_at is not None
            and record.modified_at < existing.modified_at
        ):
            return UpsertResult(
                created=False,
                skipped_stale=True,
                new_links=0,
                family_ids=tuple(p.family_id for p in existing.products),
            )

        desired: dict[int, tuple[CatalogVendor, CatalogFamily, Resolved]] = {}
        for r in resolved:
            vendor = self.catalog.vendor_for(r, record.published_date)
            family = self.catalog.family_for(vendor, r, record.published_date)
            desired.setdefault(family.id, (vendor, family, r))

        created = existing is None
        row = existing or CveRecord(cve_id=record.cve_id)
        row.published_date = record.published_date
        row.published_at = record.published_at
        row.modified_at = record.modified_at
        row.summary = record.summary
        row.link = record.link
        row.solutions = record.solutions
        row.cvss_score = record.cvss_score
        row.cvss_severity = record.cvss_severity
        row.cvss_vector = record.cvss_vector
        row.reference_urls = list(record.reference_urls)
        row.affected_lines = list(record.affected_lines)
        row.has_identity = bool(desired)
        if created:
            self.session.add(row)

        current = {p.family_id: p for p in row.products} if not created else {}
        known_vendors = {p.vendor_id for p in current.values()}
        for family_id in set(current) - set(desired):
            row.products.remove(current[family_id])
        new_links = 0
        for family_id, (vendor, family, r) in desired.items():
            if family_id in current:
                continue
            row.products.append(
                CveRecordProduct(
                    vendor_id=vendor.id,
                    family_id=family.id,
                    vendor_raw=r.vendor_display,
                    product_raw=r.family_display,
                    product_norm=r.product_norm,
                    source=r.source,
                )
            )
            family.cve_seen_total += 1
            new_links += 1
            if vendor.id not in known_vendors:
                vendor.cve_seen_total += 1
                known_vendors.add(vendor.id)
        self.session.flush()
        return UpsertResult(
            created=created,
            skipped_stale=False,
            new_links=new_links,
            family_ids=tuple(desired),
        )

    def purge_before(self, cutoff: datetime.date) -> int:
        """Hapus CVE terbit sebelum `cutoff` (anak ikut lewat FK `ON DELETE CASCADE`). TIDAK
        menyentuh katalog, statistik, `cve_tracker`, maupun ticket. Balikin jumlah CVE terhapus."""
        result = self.session.execute(delete(CveRecord).where(CveRecord.published_date < cutoff))
        self.session.expire_all()
        return int(getattr(result, "rowcount", 0) or 0)

    def purge_expired(self, today: datetime.date) -> int:
        """`purge_before(retention_cutoff(today))`: aturan tahun kalender."""
        return self.purge_before(retention_cutoff(today))
