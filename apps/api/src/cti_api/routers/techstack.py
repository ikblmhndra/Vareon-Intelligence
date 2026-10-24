"""Port CRUD inti dari `ScraperNewsWeb/app/routers/techstack.py` -- lihat
docstring `cti_core.db.repositories.techstack` buat daftar lengkap yang
SENGAJA belum diport (backfill CVE lintas-client, trigger NVD/MITRE,
cascade-delete CVE) dan alasannya (nempel `cve.py`, belum ada di sini)."""

from __future__ import annotations

from cti_core.db.models.techstack import TechStackEntry, TechStackTarget
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.techstack import AsyncTechStackRepo
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    effective_client_id,
    get_db,
    request_ip,
    require_auth,
    require_permission,
)
from cti_api.schemas.techstack import (
    TechStackAdd,
    TechStackExposureUpdate,
    TechStackHostingUpdate,
    TechStackListResponse,
    TechStackOut,
    TechStackPatch,
    TechStackTargetAdd,
    TechStackTargetOut,
)
from cti_api.services.monitor import enqueue_promote_entry

router = APIRouter(
    prefix="/api/techstack",
    tags=["techstack"],
    dependencies=[Depends(require_permission("view_cve"))],
)


def _target_out(t: TechStackTarget) -> TechStackTargetOut:
    if t.family is not None:
        return TechStackTargetOut(
            id=t.id,
            kind="family",
            family_id=t.family_id,
            label=t.family.display_name,
            vendor_label=t.family.vendor.display_name if t.family.vendor else "",
        )
    return TechStackTargetOut(
        id=t.id,
        kind="vendor",
        vendor_id=t.vendor_id,
        label=t.vendor.display_name if t.vendor else "",
    )


def _serialize(entry: TechStackEntry) -> TechStackOut:
    return TechStackOut(
        id=entry.id,
        name=entry.name,
        added_date=entry.added_date.isoformat() if entry.added_date else "",
        source=entry.source or "",
        exposure=entry.exposure or "internal",
        hosting_type=entry.hosting_type or "on_prem",
        active=entry.active,
        kind="catalog" if entry.targets else "custom",
        targets=[_target_out(t) for t in entry.targets],
    )


@router.get("", response_model=TechStackListResponse)
async def get_techstack(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = Query("name"),
    sort_dir: str = Query("asc"),
    active: bool | None = Query(
        None, description="true/false = hanya aktif/nonaktif; kosong = semua"
    ),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> TechStackListResponse:
    cid = effective_client_id(user, x_client_id)
    items, total = await AsyncTechStackRepo(session).list_filtered(
        client_id=cid,
        search=search,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        active=active,
    )
    return TechStackListResponse(
        items=[_serialize(i) for i in items], total=total, page=page, page_size=page_size
    )


@router.post("", dependencies=[Depends(require_permission("manage_cve"))])
async def post_techstack(
    body: TechStackAdd,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    """Tiga bentuk (lihat `TechStackAdd`): `name` saja = entri custom (dicocokkan lewat teks, belum
    terverifikasi katalog); `vendor_id` / `family_id` = tombol Monitor di All Tech (entri katalog
    dengan satu target). Kegagalan bisnis tetap `200 {"success": false, "reason": ...}` (kontrak
    lama): `duplicate`, `not_found`, `vendor_not_monitorable`, `invalid_target`."""
    cid = effective_client_id(user, x_client_id)
    repo = AsyncTechStackRepo(session)
    if body.vendor_id is not None or body.family_id is not None:
        entry, reason = await repo.create_from_target(
            client_id=cid,
            vendor_id=body.vendor_id,
            family_id=body.family_id,
            name=body.name,
            exposure=body.exposure,
            hosting_type=body.hosting_type,
        )
    else:
        entry, reason = await repo.create(
            name=(body.name or "").strip(),
            client_id=cid,
            exposure=body.exposure,
            hosting_type=body.hosting_type,
        )
    if entry is None:
        return {"success": False, "reason": reason}
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="add_techstack",
        target_id=entry.name,
        detail={"vendor_id": body.vendor_id, "family_id": body.family_id}
        if entry.targets
        else None,
        ip_address=request_ip(request),
    )
    await session.commit()
    if entry.targets:
        enqueue_promote_entry(entry.id)
    return {"success": True, "item": _serialize(entry).model_dump()}


@router.patch("/{tech_id}", dependencies=[Depends(require_permission("manage_cve"))])
async def patch_techstack(
    tech_id: int,
    body: TechStackPatch,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    """Aktifkan / nonaktifkan entri. Nonaktif = disembunyikan (tidak dicocokkan, tidak tampil di tab
    CVEs), TIDAK dihapus: baris `cve_tracker` dan ticket-nya tetap. Mengaktifkan kembali mengisi
    riwayatnya dari mirror (bila promosi dinyalakan)."""
    cid = effective_client_id(user, x_client_id)
    entry = await AsyncTechStackRepo(session).set_active(tech_id, cid, body.active)
    if entry is None:
        raise HTTPException(status_code=404, detail="Tech not found")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="set_techstack_active",
        target_id=str(tech_id),
        detail={"active": body.active},
        ip_address=request_ip(request),
    )
    await session.commit()
    if body.active:
        enqueue_promote_entry(tech_id)
    return {"success": True, "item": _serialize(entry).model_dump()}


_TARGET_ERRORS = {
    "entry_not_found": (404, "Tech not found"),
    "target_not_found": (404, "Target not found"),
    "not_found": (404, "Catalog vendor/family not found"),
    "target_duplicate": (409, "Target already on this tech"),
    "last_target": (
        409,
        "Cannot remove the last target; delete or deactivate the tech instead",
    ),
    "vendor_not_monitorable": (422, "This vendor has no identity; monitor a family instead"),
    "invalid_target": (422, "Provide exactly one of vendor_id / family_id"),
}


def _target_error(reason: str) -> HTTPException:
    status, detail = _TARGET_ERRORS.get(reason, (400, reason))
    return HTTPException(status_code=status, detail=detail)


@router.post("/{tech_id}/targets", dependencies=[Depends(require_permission("manage_cve"))])
async def add_techstack_target(
    tech_id: int,
    body: TechStackTargetAdd,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    """Tambah satu sasaran katalog (vendor ATAU keluarga) ke entri yang ada, mis. `junos` ->
    tiga keluarga Juniper. Kegagalan memakai status HTTP (404/409/422), bukan `success: false`."""
    cid = effective_client_id(user, x_client_id)
    entry, reason = await AsyncTechStackRepo(session).add_target(
        tech_id, cid, vendor_id=body.vendor_id, family_id=body.family_id
    )
    if entry is None:
        raise _target_error(reason)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="add_techstack_target",
        target_id=str(tech_id),
        detail={"vendor_id": body.vendor_id, "family_id": body.family_id},
        ip_address=request_ip(request),
    )
    await session.commit()
    enqueue_promote_entry(entry.id)
    return {"success": True, "item": _serialize(entry).model_dump()}


@router.delete(
    "/{tech_id}/targets/{target_id}", dependencies=[Depends(require_permission("manage_cve"))]
)
async def remove_techstack_target(
    tech_id: int,
    target_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    """Lepas satu sasaran. Target TERAKHIR tidak bisa dilepas (409): entri tanpa target kembali
    dicocokkan lewat teks nama, perubahan perilaku diam-diam. Baris `cve_tracker` yang sudah ada
    tidak dihapus."""
    cid = effective_client_id(user, x_client_id)
    entry, reason = await AsyncTechStackRepo(session).remove_target(tech_id, target_id, cid)
    if entry is None:
        raise _target_error(reason)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="remove_techstack_target",
        target_id=str(tech_id),
        detail={"target_id": target_id},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"success": True, "item": _serialize(entry).model_dump()}


@router.patch("/{tech_id}/exposure", dependencies=[Depends(require_permission("manage_cve"))])
async def patch_exposure(
    tech_id: int,
    body: TechStackExposureUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, bool]:
    cid = effective_client_id(user, x_client_id)
    ok = await AsyncTechStackRepo(session).update_exposure(tech_id, body.exposure, cid)
    if not ok:
        raise HTTPException(status_code=404, detail="Tech not found or invalid exposure value")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="update_techstack_exposure",
        target_id=str(tech_id),
        detail={"exposure": body.exposure},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"success": True}


@router.patch("/{tech_id}/hosting", dependencies=[Depends(require_permission("manage_cve"))])
async def patch_hosting(
    tech_id: int,
    body: TechStackHostingUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, bool]:
    cid = effective_client_id(user, x_client_id)
    ok = await AsyncTechStackRepo(session).update_hosting(tech_id, body.hosting_type, cid)
    if not ok:
        raise HTTPException(status_code=404, detail="Tech not found or invalid hosting type")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="update_techstack_hosting",
        target_id=str(tech_id),
        detail={"hosting_type": body.hosting_type},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"success": True}


@router.delete("/{tech_id}", dependencies=[Depends(require_permission("manage_cve"))])
async def remove_techstack(
    tech_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, bool]:
    cid = effective_client_id(user, x_client_id)
    ok = await AsyncTechStackRepo(session).delete(tech_id, cid)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="delete_techstack",
        target_id=str(tech_id),
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"success": ok}
