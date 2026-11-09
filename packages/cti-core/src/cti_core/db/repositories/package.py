"""Repository `monitored_packages`/`package_vulns`/`package_dep_graphs`.
Port dari `ScraperNewsWeb/app/services/pkg_vuln_service.py` (bagian query
Mongo doang -- fetch osv.dev/deps.dev + parsing lockfile ada di
`cti_api.services.pkg_vuln`). Fase 7.3 (router `pkg_vuln`, Bagian 4).

`_client_filter()` lama (`$or: [{client_id: "default"}, {client_id:
{$exists: false}}]`, buat nampung dokumen dari SEBELUM field `client_id`
ada) gak relevan lagi -- kolom `client_id` di sini `NOT NULL` dari awal
(gak pernah ada baris "tanpa" client_id), sama kayak `PIRRequirement.
client_id` dkk. Filter cukup `== client_id` polos."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import ColumnElement, Text, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.db.models.package import MonitoredPackage, PackageDepGraph, PackageVuln

_PKG_SORTABLE = {
    "name": MonitoredPackage.name,
    "ecosystem": MonitoredPackage.ecosystem,
    "added_date": MonitoredPackage.added_date,
    "vuln_count": MonitoredPackage.vuln_count,
    "highest_severity": MonitoredPackage.highest_severity,
    "last_scan": MonitoredPackage.last_scan,
}

_VULN_SORTABLE = {
    "advisory_id": PackageVuln.advisory_id,
    "severity": PackageVuln.severity,
    "cvss_score": PackageVuln.cvss_score,
    "adjusted_score": PackageVuln.adjusted_score,
    "epss_score": PackageVuln.epss_score,
    "published": PackageVuln.published,
    "modified": PackageVuln.modified,
    "package_name": PackageVuln.package_name,
}


class AsyncMonitoredPackageRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_filtered(
        self,
        client_id: str,
        *,
        search: str | None = None,
        ecosystem: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        sort_dir: str = "asc",
    ) -> tuple[list[MonitoredPackage], int]:
        stmt = select(MonitoredPackage).where(MonitoredPackage.client_id == client_id)
        if ecosystem:
            stmt = stmt.where(MonitoredPackage.ecosystem == ecosystem)
        if search:
            stmt = stmt.where(
                or_(
                    MonitoredPackage.name.ilike(f"%{search}%"),
                    MonitoredPackage.ecosystem.ilike(f"%{search}%"),
                )
            )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        col = _PKG_SORTABLE.get(sort_by, MonitoredPackage.name)
        order = col.asc() if sort_dir == "asc" else col.desc()
        list_stmt = stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(list_stmt)
        return list(result.scalars().all()), total

    async def get_by_name_ci(
        self, name: str, ecosystem: str, client_id: str
    ) -> MonitoredPackage | None:
        result = await self.session.execute(
            select(MonitoredPackage).where(
                func.lower(MonitoredPackage.name) == name.lower(),
                MonitoredPackage.ecosystem == ecosystem,
                MonitoredPackage.client_id == client_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, pkg_id: int, client_id: str) -> MonitoredPackage | None:
        result = await self.session.execute(
            select(MonitoredPackage).where(
                MonitoredPackage.id == pkg_id, MonitoredPackage.client_id == client_id
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        ecosystem: str,
        version: str | None,
        client_id: str,
        source: str,
        source_path: str | None = None,
    ) -> MonitoredPackage:
        pkg = MonitoredPackage(
            source_path=source_path,
            name=name,
            ecosystem=ecosystem,
            version=version,
            client_id=client_id,
            source=source,
            added_date=datetime.date.today(),
        )
        self.session.add(pkg)
        await self.session.flush()
        return pkg

    async def update_fields(self, pkg: MonitoredPackage, **fields: Any) -> MonitoredPackage:
        for k, v in fields.items():
            setattr(pkg, k, v)
        await self.session.flush()
        return pkg

    async def delete(self, pkg: MonitoredPackage) -> None:
        await self.session.delete(pkg)
        await self.session.flush()

    async def apply_scan_summary(
        self, name: str, ecosystem: str, client_id: str, **fields: Any
    ) -> bool:
        """Port `pkg_col.update_one(...)` TANPA `upsert=True` -- kalau
        gak ketemu (mis. dependensi transitif yang gak dimonitor), diem2
        no-op, sama kayak Mongo lama. Balikin apa ada baris yang ke-apply."""
        pkg = await self.get_by_name_ci(name, ecosystem, client_id)
        if pkg is None:
            return False
        for k, v in fields.items():
            setattr(pkg, k, v)
        await self.session.flush()
        return True

    async def apply_dep_resolution(self, pkg: MonitoredPackage, **fields: Any) -> None:
        for k, v in fields.items():
            setattr(pkg, k, v)
        await self.session.flush()

    async def count(self, client_id: str) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(MonitoredPackage)
            .where(MonitoredPackage.client_id == client_id)
        )
        return result.scalar_one()

    async def count_vulnerable(self, client_id: str) -> int:
        """Jumlah package yang punya minimal satu vuln (`vuln_count > 0`)."""
        result = await self.session.execute(
            select(func.count())
            .select_from(MonitoredPackage)
            .where(MonitoredPackage.client_id == client_id, MonitoredPackage.vuln_count > 0)
        )
        return result.scalar_one()


class AsyncPackageVulnRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_filtered(
        self,
        client_id: str,
        *,
        package_name: str | None = None,
        ecosystem: str | None = None,
        severity: str | None = None,
        kev_only: bool = False,
        acknowledged: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "adjusted_score",
        sort_dir: str = "desc",
    ) -> tuple[list[PackageVuln], int]:
        stmt = select(PackageVuln).where(PackageVuln.client_id == client_id)
        if package_name:
            stmt = stmt.where(PackageVuln.package_name.ilike(f"%{package_name}%"))
        if ecosystem:
            stmt = stmt.where(PackageVuln.ecosystem == ecosystem)
        if severity:
            sev = severity.upper()
            stmt = stmt.where(
                or_(PackageVuln.severity == sev, PackageVuln.adjusted_severity == sev)
            )
        if kev_only:
            stmt = stmt.where(PackageVuln.kev.is_(True))
        if acknowledged == "true":
            stmt = stmt.where(PackageVuln.acknowledged.is_(True))
        elif acknowledged == "false":
            stmt = stmt.where(PackageVuln.acknowledged.is_(False))
        if search:
            search_or: list[ColumnElement[bool]] = [
                PackageVuln.advisory_id.ilike(f"%{search}%"),
                PackageVuln.summary.ilike(f"%{search}%"),
                func.cast(PackageVuln.aliases, Text).ilike(f"%{search}%"),
            ]
            if search.isdigit():
                search_or.append(PackageVuln.id == int(search))
            stmt = stmt.where(or_(*search_or))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        col = _VULN_SORTABLE.get(sort_by, PackageVuln.adjusted_score)
        order = col.asc() if sort_dir == "asc" else col.desc()
        list_stmt = (
            stmt.order_by(order.nulls_last()).offset((page - 1) * page_size).limit(page_size)
        )
        result = await self.session.execute(list_stmt)
        return list(result.scalars().all()), total

    async def get_by_id(self, vuln_id: int, client_id: str) -> PackageVuln | None:
        result = await self.session.execute(
            select(PackageVuln).where(PackageVuln.id == vuln_id, PackageVuln.client_id == client_id)
        )
        return result.scalar_one_or_none()

    async def get_for_upsert(
        self, package_name: str, ecosystem: str, advisory_id: str, client_id: str
    ) -> PackageVuln | None:
        result = await self.session.execute(
            select(PackageVuln).where(
                PackageVuln.package_name == package_name,
                PackageVuln.ecosystem == ecosystem,
                PackageVuln.advisory_id == advisory_id,
                PackageVuln.client_id == client_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        package_name: str,
        ecosystem: str,
        advisory_id: str,
        client_id: str,
        **doc_fields: Any,
    ) -> PackageVuln:
        """Port `UpdateOne(..., {"$set": doc, "$setOnInsert": {...}}, upsert=True)`
        -- `doc_fields` isinya field hasil parsing advisory osv.dev
        (`$set`, ditimpa tiap scan). Field feedback analis (`acknowledged`/
        `ack_by`/`ack_date`) dan hasil enrichment (`epss_*`/`kev*`) itu
        `$setOnInsert` lama -- CUMA di-set pas baris BARU dibuat, gak
        pernah ketimpa scan berikutnya."""
        existing = await self.get_for_upsert(package_name, ecosystem, advisory_id, client_id)
        if existing is not None:
            for k, v in doc_fields.items():
                setattr(existing, k, v)
            await self.session.flush()
            return existing
        row = PackageVuln(
            package_name=package_name,
            ecosystem=ecosystem,
            advisory_id=advisory_id,
            client_id=client_id,
            acknowledged=False,
            ack_by=None,
            ack_date=None,
            epss_score=None,
            epss_percentile=None,
            kev=False,
            kev_date_added=None,
            **doc_fields,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete_for_package(self, package_name: str, ecosystem: str, client_id: str) -> None:
        rows = (
            (
                await self.session.execute(
                    select(PackageVuln).where(
                        PackageVuln.package_name == package_name,
                        PackageVuln.ecosystem == ecosystem,
                        PackageVuln.client_id == client_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            await self.session.delete(row)
        await self.session.flush()

    async def toggle_acknowledge(self, vuln: PackageVuln, username: str) -> bool:
        toggled = not vuln.acknowledged
        vuln.acknowledged = toggled
        if toggled:
            vuln.ack_by = username
            vuln.ack_date = datetime.datetime.now(datetime.UTC)
        else:
            vuln.ack_by = None
            vuln.ack_date = None
        await self.session.flush()
        return toggled

    async def get_severity_stats(self, client_id: str) -> dict[str, int]:
        cf = PackageVuln.client_id == client_id
        counts: dict[str, int] = {}
        for label in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            result = await self.session.execute(
                select(func.count())
                .select_from(PackageVuln)
                .where(
                    cf, or_(PackageVuln.severity == label, PackageVuln.adjusted_severity == label)
                )
            )
            counts[label.lower()] = result.scalar_one()
        total = (
            await self.session.execute(select(func.count()).select_from(PackageVuln).where(cf))
        ).scalar_one()
        unacked = (
            await self.session.execute(
                select(func.count())
                .select_from(PackageVuln)
                .where(cf, PackageVuln.acknowledged.is_(False))
            )
        ).scalar_one()
        kev_count = (
            await self.session.execute(
                select(func.count()).select_from(PackageVuln).where(cf, PackageVuln.kev.is_(True))
            )
        ).scalar_one()
        counts["total_vulns"] = total
        counts["unacknowledged"] = unacked
        counts["kev_count"] = kev_count
        return counts


class AsyncPackageDepGraphRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_pkg_id(self, pkg_id: int) -> PackageDepGraph | None:
        result = await self.session.execute(
            select(PackageDepGraph).where(PackageDepGraph.pkg_id == pkg_id)
        )
        return result.scalar_one_or_none()

    async def upsert(self, pkg_id: int, **fields: Any) -> PackageDepGraph:
        existing = await self.get_by_pkg_id(pkg_id)
        if existing is not None:
            for k, v in fields.items():
                setattr(existing, k, v)
            await self.session.flush()
            return existing
        row = PackageDepGraph(pkg_id=pkg_id, **fields)
        self.session.add(row)
        await self.session.flush()
        return row
