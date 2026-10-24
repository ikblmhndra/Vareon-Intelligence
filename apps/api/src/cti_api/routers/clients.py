"""Port 1:1 dari `ScraperNewsWeb/app/routers/clients.py`."""

from __future__ import annotations

from cti_core.db.models.auth import Client
from cti_core.db.repositories.auth import AsyncAuditLogRepo, AsyncClientRepo
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    get_db,
    request_ip,
    require_permission,
)

router = APIRouter(prefix="/api/clients", tags=["clients"])


class ClientCreate(BaseModel):
    client_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=128)
    countries: list[str] = Field(default_factory=list)


class ClientUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    # Semantik PATCH buat `countries`: omit/`null` = gak diubah. Dulu
    # default-nya `[]`, jadi payload tanpa `countries` diam-diam ngehapus
    # semua country tenant (QA BUG-01). Ngosongin harus `[]` eksplisit.
    countries: list[str] | None = None


def _serialize(client: Client) -> dict[str, object]:
    return {
        "client_id": client.client_id,
        "name": client.name,
        "countries": [c.country_code for c in client.countries],
        "created_at": client.created_at.isoformat(),
    }


@router.get("")
async def get_clients(
    session: AsyncSession = Depends(get_db),
    _admin: AuthedUser = Depends(require_permission("manage_users")),
) -> list[dict[str, object]]:
    clients = await AsyncClientRepo(session).list_all()
    return [_serialize(c) for c in clients]


@router.post("", status_code=201)
async def post_client(
    body: ClientCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    sa: AuthedUser = Depends(require_permission("manage_clients")),
) -> dict[str, object]:
    repo = AsyncClientRepo(session)
    if await repo.get(body.client_id):
        raise HTTPException(status_code=409, detail="client_id already exists")
    created = await repo.create(client_id=body.client_id, name=body.name, countries=body.countries)
    await AsyncAuditLogRepo(session).write(
        username=sa["username"],
        action="create_client",
        target_id=body.client_id,
        detail={"name": body.name, "countries": body.countries},
        ip_address=request_ip(request),
    )
    await session.commit()
    return _serialize(created)


@router.put("/{client_id}")
async def edit_client(
    client_id: str,
    body: ClientUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    sa: AuthedUser = Depends(require_permission("manage_clients")),
) -> dict[str, object]:
    updated = await AsyncClientRepo(session).update(
        client_id, name=body.name, countries=body.countries
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Client not found")
    await AsyncAuditLogRepo(session).write(
        username=sa["username"],
        action="update_client",
        target_id=client_id,
        detail={"name": body.name, "countries": [c.country_code for c in updated.countries]},
        ip_address=request_ip(request),
    )
    await session.commit()
    return _serialize(updated)


@router.delete("/{client_id}")
async def remove_client(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    sa: AuthedUser = Depends(require_permission("manage_clients")),
) -> dict[str, bool]:
    if client_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete the default client")
    ok = await AsyncClientRepo(session).delete(client_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Client not found")
    await AsyncAuditLogRepo(session).write(
        username=sa["username"],
        action="delete_client",
        target_id=client_id,
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"deleted": True}
