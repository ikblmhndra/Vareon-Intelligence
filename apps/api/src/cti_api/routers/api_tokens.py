"""Administrasi token API mesin (P7b): buat, daftar, cabut. Nilai token hanya muncul di respons
POST dan tidak pernah masuk log atau audit."""

import datetime

from cti_core.db.models import ApiToken
from cti_core.db.repositories.auth import AsyncApiTokenRepo, AsyncAuditLogRepo
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, get_db, request_ip, require_permission
from cti_api.machine_auth import API_TOKEN_SCOPES, generate_token, hash_token, token_status
from cti_api.schemas.api_token import ApiTokenCreate, ApiTokenCreated, ApiTokenOut

router = APIRouter(
    prefix="/api/api-tokens",
    tags=["api-tokens"],
    dependencies=[Depends(require_permission("manage_api_tokens"))],
)


def _out(row: ApiToken) -> dict[str, object]:
    data = {c: getattr(row, c) for c in ApiTokenOut.model_fields if c != "status"}
    data["status"] = token_status(row, datetime.datetime.now(datetime.UTC))
    return data


@router.get("", response_model=list[ApiTokenOut])
async def list_api_tokens(session: AsyncSession = Depends(get_db)) -> list[dict[str, object]]:
    return [_out(r) for r in await AsyncApiTokenRepo(session).list_all()]


@router.post("", response_model=ApiTokenCreated, status_code=201)
async def create_api_token(
    body: ApiTokenCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_permission("manage_api_tokens")),
) -> dict[str, object]:
    token = generate_token()
    expires_at = (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=body.expires_in_days)
        if body.expires_in_days is not None
        else None
    )
    row = await AsyncApiTokenRepo(session).create(
        name=body.name,
        token_prefix=token[:12],
        token_hash=hash_token(token),
        scopes=list(API_TOKEN_SCOPES),
        max_tlp=body.max_tlp,
        created_by=user["username"],
        expires_at=expires_at,
    )
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="api_token_create",
        target_id=str(row.id),
        detail={
            "name": body.name,
            "max_tlp": body.max_tlp,
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
        ip_address=request_ip(request),
    )
    await session.commit()
    await session.refresh(row)
    return {**_out(row), "token": token}


@router.delete("/{token_id}", response_model=ApiTokenOut)
async def revoke_api_token(
    token_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_permission("manage_api_tokens")),
) -> dict[str, object]:
    repo = AsyncApiTokenRepo(session)
    row = await repo.get(token_id)
    if row is None:
        raise HTTPException(status_code=404, detail="API token not found")
    await repo.revoke(row, by=user["username"])
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="api_token_revoke",
        target_id=str(token_id),
        detail={"name": row.name},
        ip_address=request_ip(request),
    )
    await session.commit()
    await session.refresh(row)
    return _out(row)
