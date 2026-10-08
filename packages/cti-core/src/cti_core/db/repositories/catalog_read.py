"""Repositori BACA async untuk API katalog dan CVE DB (ROADMAP #19, irisan 5;
`docs/CVE_CATALOG_DESIGN.md` 7). Penulisnya (ingest) ada di `repositories/catalog.py` (sync).

Katalog dan mirror GLOBAL (bukan per client); yang per client hanyalah "sudah di-Monitor atau
belum", dihitung dari `techstack_entries`/`techstack_targets` client yang meminta.

Aturan tampilan (keputusan user 2026-10-07):
- **Jelajah** (tanpa `q`) menyembunyikan keluarga yang hanya punya 1 CVE (`cve_seen_total < 2`;
  `show_all=True` menampilkan semuanya). Vendor tampil bila punya >= 1 keluarga yang tampil.
- **Pencarian** (`q`) TIDAK menyembunyikan apa pun: produk baru dengan CVE pertamanya harus tetap
  bisa ditemukan dan di-Monitor.
- Keluarga/vendor yang sudah dirujuk Monitor client ini SELALU tampil.
- Hitungan "CVE per keluarga" = `cve_seen_total`: CVE unik per keluarga, monoton naik (tidak turun
  saat retensi membuang mirror).
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.catalog_resolve import compact
from cti_core.db.models.catalog import CatalogFamily, CatalogVendor
from cti_core.db.models.cve_mirror import CveRecord, CveRecordProduct
from cti_core.db.models.techstack import TechStackEntry, TechStackTarget

HIDDEN_BELOW = 2
"""Keluarga dengan `cve_seen_total` di bawah ini disembunyikan di tampilan jelajah."""
MAX_PAGE_SIZE = 100


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like(text: str) -> str:
    """Pola ILIKE aman: `%`, `_`, dan `\\` dalam input pengguna diperlakukan literal."""
    return f"%{_escape(text)}%"


@dataclass(frozen=True)
class MonitorRef:
    entry_id: int
    active: bool


@dataclass
class MonitorMap:
    """Apa yang sudah dirujuk Monitor satu client (aktif maupun nonaktif)."""

    vendors: dict[int, MonitorRef] = field(default_factory=dict)
    families: dict[int, MonitorRef] = field(default_factory=dict)

    def vendor(self, vendor_id: int) -> MonitorRef | None:
        return self.vendors.get(vendor_id)

    def family(self, family_id: int) -> MonitorRef | None:
        return self.families.get(family_id)


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    page: int
    page_size: int
    hidden: int = 0
    """Berapa yang disembunyikan aturan jelajah (0 bila `q` / `show_all`)."""


@dataclass(frozen=True)
class VendorRow:
    vendor: CatalogVendor
    family_count: int
    visible_family_count: int
    monitor: MonitorRef | None


@dataclass(frozen=True)
class FamilyRow:
    family: CatalogFamily
    vendor: CatalogVendor
    monitor: MonitorRef | None
    vendor_monitor: MonitorRef | None
    """Monitor tingkat vendor yang menutupi keluarga ini (target vendor)."""


@dataclass(frozen=True)
class ProductRef:
    vendor_id: int
    vendor: str
    family_id: int
    family: str
    monitor: MonitorRef | None
    vendor_monitor: MonitorRef | None


@dataclass(frozen=True)
class CveDbRow:
    record: CveRecord
    products: list[ProductRef]


def _clamp(page: int, page_size: int) -> tuple[int, int]:
    return max(page, 1), min(max(page_size, 1), MAX_PAGE_SIZE)


class AsyncCatalogRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def monitor_map(self, client_id: str) -> MonitorMap:
        rows = (
            await self.session.execute(
                select(
                    TechStackTarget.vendor_id,
                    TechStackTarget.family_id,
                    TechStackEntry.id,
                    TechStackEntry.active,
                )
                .join(TechStackEntry, TechStackEntry.id == TechStackTarget.entry_id)
                .where(TechStackEntry.client_id == client_id)
                .order_by(TechStackEntry.active.desc(), TechStackEntry.id)
            )
        ).all()
        out = MonitorMap()
        for vendor_id, family_id, entry_id, active in rows:
            ref = MonitorRef(entry_id, bool(active))
            if vendor_id is not None:
                out.vendors.setdefault(vendor_id, ref)
            if family_id is not None:
                out.families.setdefault(family_id, ref)
        return out

    async def _count(self, stmt: Select[Any]) -> int:
        counted = select(func.count()).select_from(stmt.subquery())
        return (await self.session.execute(counted)).scalar_one()

    # ── vendor ────────────────────────────────────────────────────────────────────────────────

    async def list_vendors(
        self,
        *,
        client_id: str,
        q: str | None = None,
        show_all: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> Page[VendorRow]:
        page, page_size = _clamp(page, page_size)
        monitors = await self.monitor_map(client_id)
        q = (q or "").strip()

        stmt = select(CatalogVendor.id)
        hidden = 0
        if q:
            conds = [CatalogVendor.display_name.ilike(_like(q), escape="\\")]
            if compact(q):
                conds.append(CatalogVendor.key.ilike(_like(compact(q)), escape="\\"))
            stmt = stmt.where(or_(*conds))
        elif not show_all:
            visible_vendor_ids = select(CatalogFamily.vendor_id).where(
                CatalogFamily.cve_seen_total >= HIDDEN_BELOW
            )
            referenced = set(monitors.vendors)
            via_family = (
                select(CatalogFamily.vendor_id).where(CatalogFamily.id.in_(set(monitors.families)))
                if monitors.families
                else None
            )
            keep = [CatalogVendor.id.in_(visible_vendor_ids)]
            if referenced:
                keep.append(CatalogVendor.id.in_(referenced))
            if via_family is not None:
                keep.append(CatalogVendor.id.in_(via_family))
            stmt = stmt.where(or_(*keep))
            total_all = await self._count(select(CatalogVendor.id))
            hidden = max(total_all - await self._count(stmt), 0)

        total = await self._count(stmt)
        ids = (
            (
                await self.session.execute(
                    select(CatalogVendor.id)
                    .where(CatalogVendor.id.in_(stmt))
                    .order_by(CatalogVendor.cve_seen_total.desc(), CatalogVendor.display_name)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        vendors = await self._vendors_in_order(ids)
        counts = await self._family_counts(ids)
        items = [VendorRow(v, *counts.get(v.id, (0, 0)), monitors.vendor(v.id)) for v in vendors]
        return Page(items, total, page, page_size, hidden)

    async def _vendors_in_order(self, ids: Sequence[int]) -> list[CatalogVendor]:
        if not ids:
            return []
        rows = (
            (await self.session.execute(select(CatalogVendor).where(CatalogVendor.id.in_(ids))))
            .scalars()
            .all()
        )
        by_id = {v.id: v for v in rows}
        return [by_id[i] for i in ids if i in by_id]

    async def _family_counts(self, vendor_ids: Sequence[int]) -> dict[int, tuple[int, int]]:
        if not vendor_ids:
            return {}
        visible = func.count().filter(CatalogFamily.cve_seen_total >= HIDDEN_BELOW)
        rows = (
            await self.session.execute(
                select(CatalogFamily.vendor_id, func.count(), visible)
                .where(CatalogFamily.vendor_id.in_(vendor_ids))
                .group_by(CatalogFamily.vendor_id)
            )
        ).all()
        return {vid: (total, vis) for vid, total, vis in rows}

    async def get_vendor(self, vendor_id: int) -> CatalogVendor | None:
        return await self.session.get(CatalogVendor, vendor_id)

    async def get_family(self, family_id: int) -> CatalogFamily | None:
        return await self.session.get(CatalogFamily, family_id)

    # ── keluarga ──────────────────────────────────────────────────────────────────────────────

    async def list_families(
        self,
        *,
        client_id: str,
        vendor_id: int | None = None,
        q: str | None = None,
        show_all: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> Page[FamilyRow]:
        """Keluarga satu vendor (`vendor_id`), atau pencarian lintas vendor (`q` saja)."""
        page, page_size = _clamp(page, page_size)
        monitors = await self.monitor_map(client_id)
        q = (q or "").strip()

        base = select(CatalogFamily.id)
        if vendor_id is not None:
            base = base.where(CatalogFamily.vendor_id == vendor_id)
        if q:
            conds = [CatalogFamily.display_name.ilike(_like(q), escape="\\")]
            if compact(q):
                conds.append(CatalogFamily.key.ilike(_like(q.lower()), escape="\\"))
            base = base.where(or_(*conds))
        stmt = base
        hidden = 0
        if not q and not show_all:
            keep = [CatalogFamily.cve_seen_total >= HIDDEN_BELOW]
            if monitors.families:
                keep.append(CatalogFamily.id.in_(set(monitors.families)))
            stmt = base.where(or_(*keep))
            hidden = max(await self._count(base) - await self._count(stmt), 0)

        total = await self._count(stmt)
        order = [CatalogFamily.cve_seen_total.desc(), CatalogFamily.display_name]
        if q:
            order.insert(0, CatalogFamily.display_name.ilike(f"{_escape(q)}%", escape="\\").desc())
        ids = (
            (
                await self.session.execute(
                    select(CatalogFamily.id)
                    .where(CatalogFamily.id.in_(stmt))
                    .order_by(*order)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        items = await self._family_rows(ids, monitors)
        return Page(items, total, page, page_size, hidden)

    async def _family_rows(self, ids: Sequence[int], monitors: MonitorMap) -> list[FamilyRow]:
        if not ids:
            return []
        rows = (
            await self.session.execute(
                select(CatalogFamily, CatalogVendor)
                .join(CatalogVendor, CatalogVendor.id == CatalogFamily.vendor_id)
                .where(CatalogFamily.id.in_(ids))
            )
        ).all()
        by_id = {f.id: (f, v) for f, v in rows}
        return [
            FamilyRow(f, v, monitors.family(f.id), monitors.vendor(v.id))
            for f, v in (by_id[i] for i in ids if i in by_id)
        ]

    # ── CVE DB (mirror) ───────────────────────────────────────────────────────────────────────

    def _cve_filters(
        self,
        stmt: Select[tuple[str]],
        *,
        q: str | None,
        vendor_id: int | None,
        family_id: int | None,
        severity: Sequence[str] | None,
        date_start: datetime.date | None,
        date_end: datetime.date | None,
    ) -> Select[tuple[str]]:
        q = (q or "").strip()
        if q:
            stmt = stmt.where(
                or_(
                    CveRecord.cve_id.ilike(f"{_escape(q)}%", escape="\\"),
                    CveRecord.summary.ilike(_like(q), escape="\\"),
                )
            )
        if family_id is not None:
            stmt = stmt.where(
                CveRecord.cve_id.in_(
                    select(CveRecordProduct.cve_id).where(CveRecordProduct.family_id == family_id)
                )
            )
        if vendor_id is not None:
            stmt = stmt.where(
                CveRecord.cve_id.in_(
                    select(CveRecordProduct.cve_id).where(CveRecordProduct.vendor_id == vendor_id)
                )
            )
        if severity:
            stmt = stmt.where(CveRecord.cvss_severity.in_([s.upper() for s in severity]))
        if date_start is not None:
            stmt = stmt.where(CveRecord.published_date >= date_start)
        if date_end is not None:
            stmt = stmt.where(CveRecord.published_date <= date_end)
        return stmt

    async def list_cves(
        self,
        *,
        client_id: str,
        q: str | None = None,
        vendor_id: int | None = None,
        family_id: int | None = None,
        severity: Sequence[str] | None = None,
        date_start: datetime.date | None = None,
        date_end: datetime.date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page[CveDbRow]:
        page, page_size = _clamp(page, page_size)
        stmt = self._cve_filters(
            select(CveRecord.cve_id),
            q=q,
            vendor_id=vendor_id,
            family_id=family_id,
            severity=severity,
            date_start=date_start,
            date_end=date_end,
        )
        total = await self._count(stmt)
        ids = (
            (
                await self.session.execute(
                    select(CveRecord.cve_id)
                    .where(CveRecord.cve_id.in_(stmt))
                    .order_by(CveRecord.published_date.desc(), CveRecord.cve_id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return Page(await self._cve_rows(ids, client_id), total, page, page_size)

    async def get_cve(self, cve_id: str, client_id: str) -> CveDbRow | None:
        rows = await self._cve_rows([cve_id], client_id)
        return rows[0] if rows else None

    async def _cve_rows(self, ids: Sequence[str], client_id: str) -> list[CveDbRow]:
        if not ids:
            return []
        monitors = await self.monitor_map(client_id)
        records = {
            r.cve_id: r
            for r in (
                await self.session.execute(select(CveRecord).where(CveRecord.cve_id.in_(ids)))
            )
            .scalars()
            .all()
        }
        products: dict[str, list[ProductRef]] = {}
        prod_rows = (
            await self.session.execute(
                select(
                    CveRecordProduct.cve_id,
                    CatalogVendor.id,
                    CatalogVendor.display_name,
                    CatalogFamily.id,
                    CatalogFamily.display_name,
                )
                .join(CatalogVendor, CatalogVendor.id == CveRecordProduct.vendor_id)
                .join(CatalogFamily, CatalogFamily.id == CveRecordProduct.family_id)
                .where(CveRecordProduct.cve_id.in_(ids))
                .order_by(CatalogVendor.display_name, CatalogFamily.display_name)
            )
        ).all()
        for cve_id, vid, vname, fid, fname in prod_rows:
            products.setdefault(cve_id, []).append(
                ProductRef(vid, vname, fid, fname, monitors.family(fid), monitors.vendor(vid))
            )
        return [CveDbRow(records[i], products.get(i, [])) for i in ids if i in records]


__all__ = [
    "HIDDEN_BELOW",
    "AsyncCatalogRepo",
    "CveDbRow",
    "FamilyRow",
    "MonitorMap",
    "MonitorRef",
    "Page",
    "ProductRef",
    "VendorRow",
]
