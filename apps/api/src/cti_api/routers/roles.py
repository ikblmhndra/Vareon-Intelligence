"""Port 1:1 dari `ScraperNewsWeb/app/routers/roles.py`."""

from __future__ import annotations

from cti_core.db.models.auth import Role
from cti_core.db.repositories.auth import AsyncAuditLogRepo, AsyncRoleRepo
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    get_db,
    invalidate_role_permissions,
    request_ip,
    require_auth,
    require_permission,
)
from cti_api.services.roles import ALL_PERMISSIONS

router = APIRouter(prefix="/api/roles", tags=["roles"])


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=40, pattern=r"^[a-z0-9_-]+$")
    display_name: str = Field(..., min_length=1, max_length=60)
    permissions: list[str] = Field(default_factory=list)


def _serialize(role: Role) -> dict[str, object]:
    return {
        "name": role.name,
        "display_name": role.display_name,
        "permissions": role.permissions,
        "is_system": role.is_system,
        "created_by": role.created_by,
        "created_at": role.created_at.isoformat(),
    }


@router.get("/permissions")
async def get_all_permissions(
    _user: AuthedUser = Depends(require_auth),
) -> list[dict[str, str]]:
    return [{"key": k, "description": v} for k, v in ALL_PERMISSIONS.items()]


@router.get("")
async def get_roles(
    session: AsyncSession = Depends(get_db), _user: AuthedUser = Depends(require_auth)
) -> list[dict[str, object]]:
    roles = await AsyncRoleRepo(session).list_all()
    return [_serialize(r) for r in roles]


@router.post("")
async def add_role(
    body: RoleCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_permission("manage_roles")),
) -> dict[str, object]:
    unknown = [p for p in body.permissions if p not in ALL_PERMISSIONS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown permissions: {unknown}")
    repo = AsyncRoleRepo(session)
    if await repo.exists(body.name):
        raise HTTPException(status_code=409, detail=f"Role '{body.name}' already exists")
    role = await repo.create(
        name=body.name,
        display_name=body.display_name,
        permissions=body.permissions,
        created_by=admin["username"],
    )
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="create_role",
        target_id=body.name,
        detail={"permissions": body.permissions},
        ip_address=request_ip(request),
    )
    await session.commit()
    invalidate_role_permissions(body.name)
    return _serialize(role)


@router.delete("/{name}")
async def remove_role(
    name: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_permission("manage_roles")),
) -> dict[str, bool]:
    repo = AsyncRoleRepo(session)
    role = await repo.get(name)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="Cannot delete system role")
    try:
        ok = await repo.delete(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="Role not found")
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="delete_role",
        target_id=name,
        ip_address=request_ip(request),
    )
    await session.commit()
    invalidate_role_permissions(name)
    return {"ok": True}
