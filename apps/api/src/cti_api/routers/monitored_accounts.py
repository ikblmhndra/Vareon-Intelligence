"""Port dari `ScraperNewsWeb/app/routers/monitored_accounts.py`."""

from __future__ import annotations

from cti_core.db.models.tweet import MonitoredAccount
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.tweet import AsyncMonitoredAccountRepo
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    get_db,
    request_ip,
    require_auth,
    require_permission,
)
from cti_api.schemas.tweet import AddAccountRequest, MonitoredAccountOut, ToggleRequest

router = APIRouter(
    prefix="/api/monitored-accounts",
    tags=["monitored-accounts"],
    dependencies=[Depends(require_permission("view_tweets")), Depends(require_auth)],
)


def _serialize(a: MonitoredAccount) -> MonitoredAccountOut:
    return MonitoredAccountOut(
        id=a.id,
        username=a.username,
        display_name=a.display_name,
        notes=a.notes,
        active=a.active,
        added_at=a.created_at.isoformat(),
    )


@router.get("")
async def get_accounts(session: AsyncSession = Depends(get_db)) -> list[MonitoredAccountOut]:
    accounts = await AsyncMonitoredAccountRepo(session).list_all()
    return [_serialize(a) for a in accounts]


@router.post("")
async def post_account(
    body: AddAccountRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_permission("manage_tweets")),
) -> MonitoredAccountOut:
    if not body.username.strip():
        raise HTTPException(status_code=400, detail="username required")
    try:
        account = await AsyncMonitoredAccountRepo(session).create(
            body.username, body.display_name, body.notes
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="add_monitored_account",
        target_id=body.username,
        ip_address=request_ip(request),
    )
    await session.commit()
    return _serialize(account)


@router.delete("/{username}")
async def delete_account(
    username: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_permission("manage_tweets")),
) -> dict[str, bool]:
    ok = await AsyncMonitoredAccountRepo(session).remove(username)
    if not ok:
        raise HTTPException(status_code=404, detail="account not found")
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="delete_monitored_account",
        target_id=username,
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True}


@router.patch("/{username}/toggle")
async def patch_toggle(
    username: str,
    body: ToggleRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_permission("manage_tweets")),
) -> dict[str, bool]:
    ok = await AsyncMonitoredAccountRepo(session).toggle(username, body.active)
    if not ok:
        raise HTTPException(status_code=404, detail="account not found")
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="toggle_monitored_account",
        target_id=username,
        detail={"active": body.active},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True}
