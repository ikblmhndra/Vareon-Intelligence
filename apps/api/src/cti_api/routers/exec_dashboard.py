"""Port `ScraperNewsWeb/app/routers/exec_dashboard.py`. **`GET /dashboard`
(v1) SENGAJA TANPA AUTH** -- port apa adanya, kode lama juga gak nge-gate
endpoint ini (`/dashboard-v2` dan `POST /brief` iya). Asimetri yang gak
biasa (bukan pola "baca publik, tulis di-gate" -- ini "dashboard v1
publik, v2 di-gate") tapi tetap dipertahankan, bukan silent fix."""

from __future__ import annotations

import datetime

from cti_core.db.models.exec_brief import ExecBrief
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.exec_brief import AsyncExecBriefRepo
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
from cti_api.schemas.exec_brief import (
    ExecBriefDates,
    ExecBriefFilters,
    ExecBriefOut,
    ExecBriefRead,
)
from cti_api.services import exec_dashboard as exec_dashboard_service
from cti_api.services.exec_brief import (
    DEFAULT_FILTERS,
    RETENTION_DAYS,
    BriefFilters,
    BriefGenerationError,
    brief_today,
    draft_brief,
    store_brief,
)

router = APIRouter(
    prefix="/api/exec",
    tags=["exec-dashboard"],
    dependencies=[Depends(require_permission("view_intel")), Depends(require_auth)],
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


def _brief_out(row: ExecBrief) -> ExecBriefOut:
    return ExecBriefOut(
        brief_date=row.brief_date,
        markdown=row.markdown,
        filters=ExecBriefFilters(**row.filters),
        is_default_filters=row.filters == DEFAULT_FILTERS.as_json(),
        generated_at=row.generated_at,
        generated_by=row.generated_by,
        model=row.model,
        prompt_version=row.prompt_version,
    )


@router.get("/brief", response_model=ExecBriefRead)
async def read_brief(
    date: datetime.date | None = None, session: AsyncSession = Depends(get_db)
) -> ExecBriefRead:
    """Brief bersama untuk semua klien (C5): sengaja tanpa `X-Client-ID`/`effective_client_id`.
    Tanpa `date`: brief hari ini, kalau belum ada brief terbaru dalam 30 hari terakhir."""
    today = brief_today()
    repo = AsyncExecBriefRepo(session)
    if date is not None:
        row = await repo.get(date)
    else:
        row = await repo.get(today) or await repo.latest(
            since=today - datetime.timedelta(days=RETENTION_DAYS)
        )
    return ExecBriefRead(today=today, brief=_brief_out(row) if row else None)


@router.get("/brief/dates", response_model=ExecBriefDates)
async def brief_dates(session: AsyncSession = Depends(get_db)) -> ExecBriefDates:
    today = brief_today()
    dates = await AsyncExecBriefRepo(session).list_dates(
        since=today - datetime.timedelta(days=RETENTION_DAYS)
    )
    return ExecBriefDates(today=today, dates=dates)


@router.post(
    "/brief",
    response_model=ExecBriefOut,
    dependencies=[Depends(require_permission("manage_intel"))],
)
async def exec_brief(
    request: Request,
    days: int = Query(90, ge=7, le=365),
    incident_only: bool = True,
    confirmed_only: bool = False,
    user: AuthedUser = Depends(require_auth),
    session: AsyncSession = Depends(get_db),
) -> ExecBriefOut:
    """Buat ulang brief hari ini dan timpa baris bersama milik semua klien. Bentuk respons
    berubah dari `{brief, generated_at}`; web satu-satunya konsumen dan berubah di PR yang sama.
    Gagal di sisi LLM -> 502 dan baris yang ada tidak disentuh."""
    filters = BriefFilters(days, incident_only, confirmed_only)
    try:
        draft = await draft_brief(session, filters=filters)
    except BriefGenerationError as exc:
        raise HTTPException(
            status_code=502, detail="Brief generation failed. Try again later."
        ) from exc
    row = await store_brief(
        session,
        brief_date=brief_today(),
        draft=draft,
        filters=filters,
        generated_by=user["username"],
        replace=True,
    )
    assert row is not None  # replace=True selalu mengembalikan baris
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="generate_exec_brief",
        detail={**filters.as_json(), "brief_date": row.brief_date.isoformat()},
        ip_address=request_ip(request),
    )
    out = _brief_out(row)
    await session.commit()
    return out
