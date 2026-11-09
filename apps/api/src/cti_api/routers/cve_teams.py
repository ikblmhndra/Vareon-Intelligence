"""Tim pemilik CVE per client (`/api/cve/teams`): daftar dropdown ticket + kontak lead yang dipakai
draf eskalasi. `CveTicket.owner_team` tetap teks bebas, jadi rename tim merambat ke ticket di
transaksi yang sama dan hapus bersifat soft (`active=false`, ticket tidak disentuh)."""

from __future__ import annotations

from cti_core.db.models.cve import CveOwnerTeam
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.cve import AsyncCveOwnerTeamRepo
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    effective_client_id,
    get_db,
    request_ip,
    require_auth,
    require_permission,
)
from cti_api.schemas.cve_team import CveTeamIn, CveTeamListResponse, CveTeamOut, CveTeamPatch

router = APIRouter(
    prefix="/api/cve/teams",
    tags=["cve"],
    dependencies=[Depends(require_permission("view_cve"))],
)

_manage = Depends(require_permission("manage_cve"))


def _out(team: CveOwnerTeam, ticket_count: int) -> CveTeamOut:
    return CveTeamOut(
        id=team.id,
        name=team.name,
        lead_name=team.lead_name or "",
        lead_email=team.lead_email or "",
        active=team.active,
        ticket_count=ticket_count,
    )


async def _get_or_404(repo: AsyncCveOwnerTeamRepo, team_id: int, cid: str) -> CveOwnerTeam:
    team = await repo.get(team_id, cid)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.get("", response_model=CveTeamListResponse)
async def list_teams(
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> CveTeamListResponse:
    cid = effective_client_id(user, x_client_id)
    rows = await AsyncCveOwnerTeamRepo(session).list(cid, include_inactive=include_inactive)
    items = [_out(team, n) for team, n in rows]
    return CveTeamListResponse(items=items, total=len(items))


@router.post("", response_model=CveTeamOut, status_code=201, dependencies=[_manage])
async def create_team(
    body: CveTeamIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> CveTeamOut:
    cid = effective_client_id(user, x_client_id)
    repo = AsyncCveOwnerTeamRepo(session)
    if await repo.get_by_name_ci(body.name, cid) is not None:
        raise HTTPException(status_code=409, detail="Team name already exists")
    team = await repo.create(cid, body.name, body.lead_name, body.lead_email)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="cve_team_create",
        target_id=str(team.id),
        detail={"name": team.name},
        ip_address=request_ip(request),
    )
    out = _out(team, await repo.count_tickets(cid, team.name))
    await session.commit()
    return out


@router.patch("/{team_id}", response_model=CveTeamOut, dependencies=[_manage])
async def update_team(
    team_id: int,
    body: CveTeamPatch,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> CveTeamOut:
    """Rename merambat ke `owner_team` ticket client ini (satu transaksi). `409` kalau nama baru
    sudah dipakai tim lain (tanpa beda huruf besar/kecil)."""
    cid = effective_client_id(user, x_client_id)
    repo = AsyncCveOwnerTeamRepo(session)
    team = await _get_or_404(repo, team_id, cid)
    old_name = team.name
    changes = body.model_dump(exclude_unset=True)
    if changes.get("name") is None:
        changes.pop("name", None)
    if changes.get("active") is None:
        changes.pop("active", None)
    new_name = changes.get("name")
    if new_name is not None and new_name != old_name:
        clash = await repo.get_by_name_ci(new_name, cid)
        if clash is not None and clash.id != team.id:
            raise HTTPException(status_code=409, detail="Team name already exists")
        team.name = new_name
        await repo.rename_cascade(cid, old_name, new_name)
    if "lead_name" in changes:
        team.lead_name = changes["lead_name"] or None
    if "lead_email" in changes:
        team.lead_email = changes["lead_email"] or None
    if "active" in changes:
        team.active = changes["active"]
    await session.flush()
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="cve_team_update",
        target_id=str(team.id),
        detail={"fields": sorted(changes), "old_name": old_name},
        ip_address=request_ip(request),
    )
    out = _out(team, await repo.count_tickets(cid, team.name))
    await session.commit()
    return out


@router.delete("/{team_id}", dependencies=[_manage])
async def deactivate_team(
    team_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, bool]:
    """Soft delete: `active=false`. Ticket yang memakai nama tim ini tetap menyimpannya."""
    cid = effective_client_id(user, x_client_id)
    team = await _get_or_404(AsyncCveOwnerTeamRepo(session), team_id, cid)
    team.active = False
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="cve_team_deactivate",
        target_id=str(team.id),
        detail={"name": team.name},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True}
