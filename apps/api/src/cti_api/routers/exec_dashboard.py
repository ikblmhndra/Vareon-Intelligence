"""Port `ScraperNewsWeb/app/routers/exec_dashboard.py`. **`GET /dashboard`
(v1) SENGAJA TANPA AUTH** -- port apa adanya, kode lama juga gak nge-gate
endpoint ini (`/dashboard-v2` dan `POST /brief` iya). Asimetri yang gak
biasa (bukan pola "baca publik, tulis di-gate" -- ini "dashboard v1
publik, v2 di-gate") tapi tetap dipertahankan, bukan silent fix."""

from __future__ import annotations

import datetime

from cti_core.db.repositories.auth import AsyncAuditLogRepo
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, effective_client_id, get_db, request_ip, require_auth
from cti_api.services import exec_brief as exec_brief_service
from cti_api.services import exec_dashboard as exec_dashboard_service

router = APIRouter(
    prefix="/api/exec", tags=["exec-dashboard"], dependencies=[Depends(require_auth)]
)


@router.get("/dashboard")
async def dashboard_v1(
    days: int = Query(90, ge=7, le=365),
    incident_only: bool = True,
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await exec_dashboard_service.get_exec_dashboard(
        session, days=days, incident_only=incident_only
    )


@router.get("/dashboard-v2")
async def dashboard_v2(
    days: int = Query(90, ge=7, le=365),
    incident_only: bool = True,
    confirmed_only: bool = False,
    role: str | None = Query(None, description="Role preview — admin only"),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    effective_role = user.get("role", "analyst")
    if role is not None:
        if user["role"] not in ("admin", "superadmin"):
            raise HTTPException(status_code=403, detail="Role preview is admin-only")
        await AsyncAuditLogRepo(session).write(
            username=user["username"],
            action="exec_dashboard_role_preview",
            detail={"preview_role": role},
        )
        effective_role = role
    result = await exec_dashboard_service.get_exec_dashboard_v2(
        session,
        days=days,
        incident_only=incident_only,
        confirmed_only=confirmed_only,
        client_id=cid,
        role=effective_role,
    )
    await session.commit()
    return result


@router.post("/brief")
async def exec_brief(
    request: Request,
    days: int = Query(90),
    incident_only: bool = True,
    confirmed_only: bool = False,
    user: AuthedUser = Depends(require_auth),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    text = await exec_brief_service.generate_exec_brief(
        session, days, incident_only, confirmed_only
    )
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="generate_exec_brief",
        detail={"days": days, "incident_only": incident_only, "confirmed_only": confirmed_only},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"brief": text, "generated_at": datetime.datetime.now(datetime.UTC).isoformat()}
