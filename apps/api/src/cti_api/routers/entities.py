"""API entitas P7c (spec 5.2): `/api/entities` dan `/api/relationships`, JWT web.

Permission per endpoint persis tabel spec (dicek `tests/unit/test_route_permissions.py`): baca
`view_ta`, tulis `manage_entities`, watch `manage_pir`, profil LLM `manage_intel`. Router tipis;
logika di `services/entities.py`. 409 selalu `{detail}` (pesan dari service / `EntityMergeError`,
mis. split tanpa alias nama sendiri, Ruling 17). Endpoint TA/ATT&CK lama tetap ada sampai P7c-2.
"""

from __future__ import annotations

from collections.abc import Awaitable

from cti_core.entity import ENTITY_TYPES
from cti_core.logging import get_logger
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, effective_client_id, get_db, request_ip, require_permission
from cti_api.schemas.entities import (
    AliasCreate,
    AliasOut,
    EntityAttackResponse,
    EntityCreate,
    EntityCvesResponse,
    EntityDetail,
    EntityIndicatorsResponse,
    EntityListResponse,
    EntityProfileOut,
    EntityRef,
    EntityRelationshipsResponse,
    EntityStoriesResponse,
    EntityTimelineResponse,
    EntityUpdate,
    MergeBody,
    MergeResultOut,
    RelationshipCreate,
    RelationshipOut,
    SplitBody,
    WatchOut,
)
from cti_api.services import entities as svc

router = APIRouter(prefix="/api/entities", tags=["entities"])
relationships_router = APIRouter(prefix="/api/relationships", tags=["entities"])
log = get_logger()

_view = require_permission("view_ta")
_manage = require_permission("manage_entities")
_watch = require_permission("manage_pir")
_profile = require_permission("manage_intel")


async def _call[T](session: AsyncSession, op: Awaitable[T]) -> T:
    """Kesalahan bisnis -> 404/409 `{detail}`; tulisan yang sudah di-flush dibatalkan."""
    try:
        return await op
    except svc.EntityNotFound as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except svc.EntityConflict as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        # Ruling 29: balapan dua request (cek di service lolos, indeks unik menolak) -> 409
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="conflicting change, reload and try again"
        ) from exc


def _check_types(type_: str | None) -> list[str]:
    """Daftar tipe dipisah koma -> list; tipe di luar `ENTITY_TYPES` = 422."""
    types = [t for t in (type_ or "").split(",") if t]
    bad = [t for t in types if t not in ENTITY_TYPES]
    if bad:
        raise HTTPException(status_code=422, detail=f"unknown entity type: {', '.join(bad)}")
    return types


@router.get("", response_model=EntityListResponse)
async def list_entities(
    type: str | None = None,
    identity_class: str | None = None,
    q: str | None = None,
    watched: bool = False,
    include_suppressed: bool = False,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_view),
) -> EntityListResponse:
    _check_types(type)
    try:
        return await svc.list_entities(
            session,
            client_id=effective_client_id(user, x_client_id),
            type=type,
            identity_class=identity_class,
            q=q,
            watched=watched,
            include_suppressed=include_suppressed,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:  # kursor cacat
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", response_model=EntityDetail, status_code=201)
async def create_entity(
    body: EntityCreate,
    request: Request,
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_manage),
) -> EntityDetail:
    entity_id = await _call(
        session,
        svc.create_entity(session, body, actor=user["username"], ip=request_ip(request)),
    )
    await session.commit()
    return await svc.entity_detail(session, entity_id, effective_client_id(user, x_client_id))


@router.get("/resolve", response_model=EntityRef)
async def resolve_entity(
    type: str,
    name: str,
    session: AsyncSession = Depends(get_db),
    _user: AuthedUser = Depends(_view),
) -> EntityRef:
    """Nama teks -> entitas (alias, external_id, ikuti merge). Harus sebelum `/{entity_id}`."""
    types = _check_types(type)
    if not types:
        raise HTTPException(status_code=422, detail="type is required")
    ref = await svc.resolve_entity(session, types, name)
    if ref is None:
        raise HTTPException(status_code=404, detail=f"no entity named {name}")
    return ref


@router.get("/{entity_id}", response_model=EntityDetail)
async def get_entity(
    entity_id: int,
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_view),
) -> EntityDetail:
    return await _call(
        session, svc.entity_detail(session, entity_id, effective_client_id(user, x_client_id))
    )


@router.patch("/{entity_id}", response_model=EntityDetail)
async def update_entity(
    entity_id: int,
    body: EntityUpdate,
    request: Request,
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_manage),
) -> EntityDetail:
    await _call(
        session,
        svc.update_entity(session, entity_id, body, actor=user["username"], ip=request_ip(request)),
    )
    await session.commit()
    return await svc.entity_detail(session, entity_id, effective_client_id(user, x_client_id))


@router.get("/{entity_id}/relationships", response_model=EntityRelationshipsResponse)
async def get_relationships(
    entity_id: int,
    session: AsyncSession = Depends(get_db),
    _user: AuthedUser = Depends(_view),
) -> EntityRelationshipsResponse:
    return await _call(session, svc.entity_relationships(session, entity_id))


@router.get("/{entity_id}/stories", response_model=EntityStoriesResponse)
async def get_stories(
    entity_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    _user: AuthedUser = Depends(_view),
) -> EntityStoriesResponse:
    return await _call(session, svc.entity_stories(session, entity_id, limit=limit, offset=offset))


@router.get("/{entity_id}/indicators", response_model=EntityIndicatorsResponse)
async def get_indicators(
    entity_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    _user: AuthedUser = Depends(_view),
) -> EntityIndicatorsResponse:
    return await _call(
        session, svc.entity_indicators(session, entity_id, limit=limit, offset=offset)
    )


@router.get("/{entity_id}/cves", response_model=EntityCvesResponse)
async def get_cves(
    entity_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_view),
) -> EntityCvesResponse:
    return await _call(
        session,
        svc.entity_cves(
            session,
            entity_id,
            effective_client_id(user, x_client_id),
            limit=limit,
            offset=offset,
        ),
    )


@router.get("/{entity_id}/timeline", response_model=EntityTimelineResponse)
async def get_timeline(
    entity_id: int,
    months: int = Query(24, ge=3, le=60),
    session: AsyncSession = Depends(get_db),
    _user: AuthedUser = Depends(_view),
) -> EntityTimelineResponse:
    return await _call(session, svc.entity_timeline(session, entity_id, months=months))


@router.get("/{entity_id}/attack", response_model=EntityAttackResponse)
async def get_attack(
    entity_id: int,
    session: AsyncSession = Depends(get_db),
    _user: AuthedUser = Depends(_view),
) -> EntityAttackResponse:
    return await _call(session, svc.entity_attack(session, entity_id))


@router.post("/{entity_id}/aliases", response_model=AliasOut, status_code=201)
async def add_alias(
    entity_id: int,
    body: AliasCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_manage),
) -> AliasOut:
    out = await _call(
        session,
        svc.add_alias(
            session, entity_id, body.alias, actor=user["username"], ip=request_ip(request)
        ),
    )
    await session.commit()
    return out


@router.delete("/{entity_id}/aliases/{alias_id}", response_model=EntityDetail)
async def remove_alias(
    entity_id: int,
    alias_id: int,
    request: Request,
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_manage),
) -> EntityDetail:
    await _call(
        session,
        svc.remove_alias(
            session, entity_id, alias_id, actor=user["username"], ip=request_ip(request)
        ),
    )
    await session.commit()
    return await svc.entity_detail(session, entity_id, effective_client_id(user, x_client_id))


@router.get("/{entity_id}/merge-preview", response_model=MergeResultOut)
async def merge_preview(
    entity_id: int,
    into_id: int,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_manage),
) -> MergeResultOut:
    result = await _call(
        session,
        svc.merge(session, entity_id, into_id, actor=user["username"], preview=True),
    )
    return MergeResultOut(**vars(result))


@router.post("/{entity_id}/merge", response_model=MergeResultOut)
async def merge(
    entity_id: int,
    body: MergeBody,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_manage),
) -> MergeResultOut:
    """Audit ditulis `merge_entities` (actor = username)."""
    result = await _call(
        session,
        svc.merge(session, entity_id, body.into_id, actor=user["username"], preview=False),
    )
    await session.commit()
    return MergeResultOut(**vars(result))


@router.post("/{entity_id}/split", response_model=EntityDetail)
async def split(
    entity_id: int,
    body: SplitBody,
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_manage),
) -> EntityDetail:
    """Mengembalikan entitas baru atau tombstone yang dihidupkan lagi."""
    target_id = await _call(
        session, svc.split(session, entity_id, body.alias_ids, actor=user["username"])
    )
    await session.commit()
    return await svc.entity_detail(session, target_id, effective_client_id(user, x_client_id))


@router.put("/{entity_id}/watch", response_model=WatchOut)
async def watch(
    entity_id: int,
    request: Request,
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_watch),
) -> WatchOut:
    cid = effective_client_id(user, x_client_id)
    watched = await _call(
        session,
        svc.set_watch(
            session, entity_id, cid, True, actor=user["username"], ip=request_ip(request)
        ),
    )
    await session.commit()
    return WatchOut(watched=watched)


@router.delete("/{entity_id}/watch", response_model=WatchOut)
async def unwatch(
    entity_id: int,
    request: Request,
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_watch),
) -> WatchOut:
    cid = effective_client_id(user, x_client_id)
    watched = await _call(
        session,
        svc.set_watch(
            session, entity_id, cid, False, actor=user["username"], ip=request_ip(request)
        ),
    )
    await session.commit()
    return WatchOut(watched=watched)


@router.post("/{entity_id}/profile", response_model=EntityProfileOut)
async def generate_profile(
    entity_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_profile),
) -> EntityProfileOut:
    try:
        profile = await _call(
            session,
            svc.generate_profile(
                session, entity_id, actor=user["username"], ip=request_ip(request)
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:  # kegagalan LLM -> 500; detail generik, rinciannya ke log
        log.exception("entity_profile_generate_failed", entity_id=entity_id)
        raise HTTPException(status_code=500, detail="profile generation failed") from exc
    await session.commit()
    return EntityProfileOut(profile=profile)


@relationships_router.post("", response_model=RelationshipOut, status_code=201)
async def create_relationship(
    body: RelationshipCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_manage),
) -> RelationshipOut:
    """Relasi analis (termasuk "make relationship" dari co-mention); confidence default 75."""
    out = await _call(
        session,
        svc.create_relationship(session, body, actor=user["username"], ip=request_ip(request)),
    )
    await session.commit()
    return out


@relationships_router.delete("/{relationship_id}", response_model=RelationshipOut)
async def revoke_relationship(
    relationship_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(_manage),
) -> RelationshipOut:
    """Hapus = revoke (terbit `revoked: true`); idempoten."""
    out = await _call(
        session,
        svc.revoke_relationship(
            session, relationship_id, actor=user["username"], ip=request_ip(request)
        ),
    )
    await session.commit()
    return out
