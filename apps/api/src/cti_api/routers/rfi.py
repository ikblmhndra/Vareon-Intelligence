"""Port dari `ScraperNewsWeb/app/routers/rfi.py`. Asimetri client-scoping
(list/get/create di-filter client_id, update/delete TIDAK) port apa
adanya dari kode lama -- lihat docstring `cti_core.db.repositories.rfi`."""

from __future__ import annotations

from cti_core.db.models.rfi import RFIRequest
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.rfi import AsyncRFIRepo
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    effective_client_id,
    ensure_client_access,
    get_db,
    request_ip,
    require_auth,
)
from cti_api.schemas.rfi import RFICreate, RFIListResponse, RFIOut, RFIUpdate

router = APIRouter(prefix="/api/rfi", tags=["rfi"])


def _serialize(rfi: RFIRequest) -> RFIOut:
    return RFIOut(
        id=rfi.id,
        requester=rfi.requester,
        question=rfi.question,
        due_date=rfi.due_date.isoformat() if rfi.due_date else None,
        status=rfi.status,
        linked_pir=rfi.linked_pir_id,
        response=rfi.response,
        created_at=rfi.created_at.isoformat(),
        updated_at=rfi.updated_at.isoformat(),
    )


@router.get("", response_model=RFIListResponse)
async def get_rfis(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> RFIListResponse:
    cid = effective_client_id(user, x_client_id)
    rfis, total = await AsyncRFIRepo(session).list_filtered(
        client_id=cid, status=status, page=page, page_size=page_size
    )
    return RFIListResponse(
        rfis=[_serialize(r) for r in rfis], total=total, page=page, page_size=page_size
    )


@router.get("/{rfi_id}", response_model=RFIOut)
async def get_rfi_by_id(
    rfi_id: int,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> RFIOut:
    cid = effective_client_id(user, x_client_id)
    rfi = await AsyncRFIRepo(session).get_by_id(rfi_id, cid)
    if rfi is None:
        raise HTTPException(status_code=404, detail="RFI not found")
    return _serialize(rfi)


@router.post("", response_model=RFIOut)
async def post_rfi(
    body: RFICreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> RFIOut:
    cid = effective_client_id(user, x_client_id)
    rfi = await AsyncRFIRepo(session).create(body.model_dump(), client_id=cid)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="create_rfi",
        detail={"question": body.question[:80]},
        ip_address=request_ip(request),
    )
    await session.commit()
    return _serialize(rfi)


async def _ensure_rfi_access(repo: AsyncRFIRepo, rfi_id: int, user: AuthedUser) -> None:
    rfi = await repo.get_by_id_unscoped(rfi_id)
    if rfi is None:
        raise HTTPException(status_code=404, detail="RFI not found")
    ensure_client_access(user, rfi.client_id)


@router.put("/{rfi_id}", response_model=RFIOut)
async def put_rfi(
    rfi_id: int,
    body: RFIUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> RFIOut:
    repo = AsyncRFIRepo(session)
    await _ensure_rfi_access(repo, rfi_id, user)
    rfi = await repo.update(rfi_id, body.model_dump(exclude_none=True))
    if rfi is None:
        raise HTTPException(status_code=404, detail="RFI not found")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="update_rfi",
        target_id=str(rfi_id),
        ip_address=request_ip(request),
    )
    await session.commit()
    # `updated_at` server-computed (`onupdate=func.now()`) -- lihat catatan
    # sama di `pir.py::put_pir` (bug `MissingGreenlet` yang beneran ketemu
    # live-test, bukan hipotesis).
    await session.refresh(rfi)
    return _serialize(rfi)


@router.delete("/{rfi_id}")
async def remove_rfi(
    rfi_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    repo = AsyncRFIRepo(session)
    await _ensure_rfi_access(repo, rfi_id, user)
    ok = await repo.delete(rfi_id)
    if not ok:
        raise HTTPException(status_code=404, detail="RFI not found")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="delete_rfi",
        target_id=str(rfi_id),
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"deleted": True}
