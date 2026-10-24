"""Port `ScraperNewsWeb/app/routers/pkg_vuln.py`. SELURUH router ini
`require_auth` -- gak ada asimetri baca-vs-tulis (sama kayak `attack.py`),
tiap endpoint juga butuh objek user buat `effective_client_id(user,
x_client_id)`, jadi `Depends(require_auth)` dideklarasi per-endpoint
(bukan `dependencies=[]` level-router kayak `attack.py`, yang separuh
endpoint-nya gak butuh objek user).

`pkg_id`/`vuln_id` sekarang `int` (Postgres bigint), bukan Mongo ObjectId
hex string -- penyesuaian skema yang sama kayak router lain.

**Fire-and-forget scan (`asyncio.create_task(scan_package(...))` dkk
lama) jadi `BackgroundTasks` FastAPI + sesi baru per task** -- pola
persis `routers/attack.py` (lihat docstring modul itu buat alasan
lengkap: sesi request ketutup begitu response dikirim). `resolve-deps`
dengan `scan_transitive=True` nge-spawn LEBIH BANYAK task lagi dari
DALAM task background pertama (`asyncio.create_task` mentah, bukan
`BackgroundTasks` -- kita udah lewat siklus request/response di titik
itu, jadi `BackgroundTasks` FastAPI yang terikat ke request gak relevan
lagi, tiap task tetap dapet sesi sendiri)."""

from __future__ import annotations

import asyncio

from cti_core.db.engine import async_session
from cti_core.db.models.package import MonitoredPackage, PackageVuln
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.package import (
    AsyncMonitoredPackageRepo,
    AsyncPackageDepGraphRepo,
    AsyncPackageVulnRepo,
)
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    effective_client_id,
    get_db,
    request_ip,
    require_auth,
    require_permission,
)
from cti_api.schemas.pkg_vuln import (
    LockfileImportResult,
    MonitoredPackageAddBody,
    MonitoredPackageEditBody,
    MonitoredPackageListResponse,
    MonitoredPackageOut,
    PackageDepGraphOut,
    PackageVulnListResponse,
    PackageVulnOut,
)
from cti_api.services import pkg_vuln as pkg_vuln_service

_MAX_LOCKFILE_BYTES = 2_000_000

router = APIRouter(
    prefix="/api/pkgvuln", tags=["pkgvuln"], dependencies=[Depends(require_permission("view_cve"))]
)


# ── Background task wrappers -- lihat docstring modul ───────────────────────


async def _run_scan_package(name: str, ecosystem: str, version: str | None, client_id: str) -> None:
    async with async_session() as session:
        try:
            await pkg_vuln_service.scan_package(session, name, ecosystem, version, client_id)
            await session.commit()
        except Exception as e:
            print(f"[pkg_vuln] scan {name}/{ecosystem} failed: {e}")


async def _run_scan_all(client_id: str) -> None:
    async with async_session() as session:
        try:
            await pkg_vuln_service.scan_all_packages(session, client_id)
            await session.commit()
        except Exception as e:
            print(f"[pkg_vuln] scan-all ({client_id}) failed: {e}")


async def _run_resolve_deps(pkg_id: int, client_id: str, scan_transitive: bool) -> None:
    async with async_session() as session:
        try:
            result = await pkg_vuln_service.resolve_package_deps(
                session, pkg_id, client_id, scan_transitive
            )
            await session.commit()
        except Exception as e:
            print(f"[pkg_vuln] resolve-deps {pkg_id} failed: {e}")
            return
    for target in result.get("transitive_targets", []):
        asyncio.create_task(  # noqa: RUF006 -- fire-and-forget di luar siklus request, port apa adanya
            _run_scan_package(target["name"], target["ecosystem"], target["version"], client_id)
        )


def _pkg_out(pkg: MonitoredPackage) -> MonitoredPackageOut:
    return MonitoredPackageOut(
        id=pkg.id,
        name=pkg.name,
        ecosystem=pkg.ecosystem,
        version=pkg.version,
        client_id=pkg.client_id,
        added_date=pkg.added_date.isoformat(),
        last_scan=pkg.last_scan.isoformat() if pkg.last_scan else None,
        vuln_count=pkg.vuln_count,
        critical_count=pkg.critical_count,
        high_count=pkg.high_count,
        medium_count=pkg.medium_count,
        low_count=pkg.low_count,
        highest_severity=pkg.highest_severity,
        latest_version=pkg.latest_version,
        source=pkg.source,
        dep_direct_count=pkg.dep_direct_count,
        dep_indirect_count=pkg.dep_indirect_count,
        dep_total_count=pkg.dep_total_count,
        dep_resolved_at=pkg.dep_resolved_at.isoformat() if pkg.dep_resolved_at else None,
        scorecard_score=pkg.scorecard_score,
        scorecard_date=pkg.scorecard_date,
    )


def _vuln_out(v: PackageVuln) -> PackageVulnOut:
    return PackageVulnOut(
        id=v.id,
        package_name=v.package_name,
        ecosystem=v.ecosystem,
        pinned_version=v.pinned_version,
        advisory_id=v.advisory_id,
        aliases=v.aliases,
        summary=v.summary,
        details=v.details,
        severity=v.severity,
        cvss_score=v.cvss_score,
        epss_score=v.epss_score,
        epss_percentile=v.epss_percentile,
        kev=v.kev,
        kev_date_added=v.kev_date_added,
        adjusted_score=v.adjusted_score,
        adjusted_severity=v.adjusted_severity,
        published=v.published.isoformat() if v.published else None,
        modified=v.modified.isoformat() if v.modified else None,
        fixed_version=v.fixed_version,
        affected_version_ranges=v.affected_version_ranges,
        references=v.references,
        client_id=v.client_id,
        acknowledged=v.acknowledged,
        ack_by=v.ack_by,
        ack_date=v.ack_date.isoformat() if v.ack_date else None,
        source=v.source,
    )


# ── Packages ──────────────────────────────────────────────────────────────────


@router.get("/packages", response_model=MonitoredPackageListResponse)
async def get_packages(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = Query("name"),
    sort_dir: str = Query("asc"),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> MonitoredPackageListResponse:
    cid = effective_client_id(user, x_client_id)
    items, total = await AsyncMonitoredPackageRepo(session).list_filtered(
        cid, search=search, page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir
    )
    return MonitoredPackageListResponse(
        items=[_pkg_out(i) for i in items], total=total, page=page, page_size=page_size
    )


@router.post("/packages", dependencies=[Depends(require_permission("manage_cve"))])
async def post_package(
    body: MonitoredPackageAddBody,
    request: Request,
    background_tasks: BackgroundTasks,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    result = await pkg_vuln_service.add_package(
        session, body.name, body.ecosystem, version=body.version, client_id=cid
    )
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("reason", "error"))
    background_tasks.add_task(_run_scan_package, body.name, body.ecosystem, body.version, cid)
    ver_str = f"@{body.version}" if body.version else ""
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="add_monitored_package",
        target_id=f"{body.name}{ver_str}/{body.ecosystem}",
        ip_address=request_ip(request),
    )
    await session.commit()
    return result


@router.patch("/packages/{pkg_id}", dependencies=[Depends(require_permission("manage_cve"))])
async def patch_package(
    pkg_id: int,
    body: MonitoredPackageEditBody,
    request: Request,
    background_tasks: BackgroundTasks,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    result = await pkg_vuln_service.update_package(
        session, pkg_id, version=body.version, ecosystem=body.ecosystem, client_id=cid
    )
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("reason", "not found"))
    if result.get("rescan"):
        background_tasks.add_task(
            _run_scan_package, result["name"], result["ecosystem"], result["version"], cid
        )
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="edit_monitored_package",
        target_id=str(pkg_id),
        ip_address=request_ip(request),
    )
    await session.commit()
    return result


@router.delete("/packages/{pkg_id}", dependencies=[Depends(require_permission("manage_cve"))])
async def remove_package(
    pkg_id: int,
    request: Request,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    result = await pkg_vuln_service.delete_package(session, pkg_id, client_id=cid)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("reason", "not found"))
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="delete_monitored_package",
        target_id=str(pkg_id),
        ip_address=request_ip(request),
    )
    await session.commit()
    return result


@router.post(
    "/packages/{pkg_id}/resolve-deps", dependencies=[Depends(require_permission("manage_cve"))]
)
async def resolve_deps(
    pkg_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    scan_transitive: bool = Query(False),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    pkg = await AsyncMonitoredPackageRepo(session).get_by_id(pkg_id, cid)
    if pkg is None:
        raise HTTPException(status_code=404, detail="Package not found")
    background_tasks.add_task(_run_resolve_deps, pkg_id, cid, scan_transitive)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="resolve_package_deps",
        target_id=f"{pkg.name}/{pkg.ecosystem}",
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"started": True, "package": pkg.name, "ecosystem": pkg.ecosystem}


@router.get("/packages/{pkg_id}/deps", response_model=PackageDepGraphOut)
async def get_deps(
    pkg_id: int,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> PackageDepGraphOut:
    cid = effective_client_id(user, x_client_id)
    pkg = await AsyncMonitoredPackageRepo(session).get_by_id(pkg_id, cid)
    if pkg is None:
        raise HTTPException(status_code=404, detail="Package not found")
    result = await AsyncPackageDepGraphRepo(session).get_by_pkg_id(pkg_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No dependency graph found — resolve first")
    return PackageDepGraphOut(
        id=result.id,
        pkg_id=result.pkg_id,
        package_name=result.package_name,
        ecosystem=result.ecosystem,
        version=result.version,
        resolved_at=result.resolved_at.isoformat(),
        direct_count=result.direct_count,
        indirect_count=result.indirect_count,
        total_count=result.total_count,
        direct_deps=result.direct_deps,
        indirect_deps=result.indirect_deps,
        scorecard_score=result.scorecard_score,
        scorecard_date=result.scorecard_date,
        scorecard_project=result.scorecard_project,
        scorecard_checks=result.scorecard_checks,
        error=result.error,
    )


@router.post("/packages/{pkg_id}/scan", dependencies=[Depends(require_permission("manage_cve"))])
async def scan_one_package(
    pkg_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    pkg = await AsyncMonitoredPackageRepo(session).get_by_id(pkg_id, cid)
    if pkg is None:
        raise HTTPException(status_code=404, detail="Package not found")
    background_tasks.add_task(_run_scan_package, pkg.name, pkg.ecosystem, pkg.version, cid)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="scan_package",
        target_id=f"{pkg.name}/{pkg.ecosystem}",
        ip_address=request_ip(request),
    )
    await session.commit()
    return {
        "started": True,
        "package": pkg.name,
        "ecosystem": pkg.ecosystem,
        "version": pkg.version,
    }


@router.post("/scan", dependencies=[Depends(require_permission("manage_cve"))])
async def scan_all(
    request: Request,
    background_tasks: BackgroundTasks,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    background_tasks.add_task(_run_scan_all, cid)
    await AsyncAuditLogRepo(session).write(
        username=user["username"], action="scan_all_packages", ip_address=request_ip(request)
    )
    await session.commit()
    return {"started": True}


@router.post(
    "/import-lockfile",
    dependencies=[Depends(require_permission("manage_cve"))],
    response_model=LockfileImportResult,
)
async def import_lockfile_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> LockfileImportResult:
    """Upload lockfile (requirements.txt, package-lock.json, go.mod,
    pom.xml, poetry.lock). Parse package dengan versi pinned, tambahin
    ke monitoring."""
    cid = effective_client_id(user, x_client_id)
    content_bytes = await file.read(_MAX_LOCKFILE_BYTES + 1)  # jangan baca upload tak terbatas
    if len(content_bytes) > _MAX_LOCKFILE_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 2 MB)")
    try:
        content = content_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=400, detail="Could not decode file as UTF-8") from e
    result = await pkg_vuln_service.import_lockfile(
        session, file.filename or "unknown", content, client_id=cid
    )
    for pkg in result["packages"]:
        background_tasks.add_task(
            _run_scan_package, pkg["name"], pkg["ecosystem"], pkg.get("version"), cid
        )
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="import_lockfile",
        target_id=file.filename or "unknown",
        detail={"parsed": result["parsed"], "added": result["added"]},
        ip_address=request_ip(request),
    )
    await session.commit()
    return LockfileImportResult(**result)


# ── Vulnerabilities ────────────────────────────────────────────────────────────


@router.get("/vulns", response_model=PackageVulnListResponse)
async def get_vulns(
    package_name: str | None = None,
    ecosystem: str | None = None,
    severity: str | None = None,
    kev_only: bool = Query(False),
    acknowledged: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = Query("adjusted_score"),
    sort_dir: str = Query("desc"),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> PackageVulnListResponse:
    cid = effective_client_id(user, x_client_id)
    items, total = await AsyncPackageVulnRepo(session).list_filtered(
        cid,
        package_name=package_name,
        ecosystem=ecosystem,
        severity=severity,
        kev_only=kev_only,
        acknowledged=acknowledged,
        search=search,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return PackageVulnListResponse(
        items=[_vuln_out(i) for i in items], total=total, page=page, page_size=page_size
    )


@router.patch("/vulns/{vuln_id}/ack", dependencies=[Depends(require_permission("manage_cve"))])
async def ack_vuln(
    vuln_id: int,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    vuln_repo = AsyncPackageVulnRepo(session)
    vuln = await vuln_repo.get_by_id(vuln_id, cid)
    if vuln is None:
        raise HTTPException(status_code=404, detail="not found")
    toggled = await vuln_repo.toggle_acknowledge(vuln, user["username"])
    await session.commit()
    return {"success": True, "acknowledged": toggled}


# ── Stats ──────────────────────────────────────────────────────────────────────


@router.get("/stats")
async def get_pkg_stats(
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    pkg_count = await AsyncMonitoredPackageRepo(session).count(cid)
    vuln_stats = await AsyncPackageVulnRepo(session).get_severity_stats(cid)
    return {
        "packages": pkg_count,
        "total_vulns": vuln_stats["total_vulns"],
        "critical": vuln_stats["critical"],
        "high": vuln_stats["high"],
        "medium": vuln_stats["medium"],
        "low": vuln_stats["low"],
        "unacknowledged": vuln_stats["unacknowledged"],
        "kev_count": vuln_stats["kev_count"],
    }
