"""Feed entitas dan relasi REST untuk mesin (P7c spec 5.3), pola feed indikator P7b: TLP per
token, settle lag 60 s, kursor keyset `(feed_changed_at, id)`. Auth `require_token("intel:read")`,
bukan JWT. Hanya JSON (CSV khusus feed indikator)."""

from __future__ import annotations

import datetime

from cti_core.entity import ENTITY_TYPES, RELATIONSHIP_TYPES
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import get_db
from cti_api.machine_auth import MachinePrincipal, require_token
from cti_api.schemas.feed import (
    EntityFeedItem,
    EntityFeedPage,
    RelationshipFeedItem,
    RelationshipFeedPage,
)
from cti_api.services.feed import (
    EntityRow,
    RelationshipRow,
    decode_cursor,
    entity_feed_page,
    relationship_feed_page,
)

router = APIRouter(prefix="/api/v2", tags=["machine-api"])


def _common(
    changed_after: datetime.datetime | None, cursor: str | None
) -> tuple[datetime.datetime, int] | None:
    """Validasi bersama dengan `/api/v2/indicators`; balikan kursor terdekode."""
    if changed_after is not None and changed_after.tzinfo is None:
        raise HTTPException(400, "changed_after must include a timezone offset")
    if changed_after is not None:
        try:
            changed_after.astimezone(datetime.UTC)
        except OverflowError:
            raise HTTPException(400, "changed_after is out of range") from None
    if cursor is None:
        return None
    try:
        return decode_cursor(cursor)
    except ValueError:
        raise HTTPException(400, "Invalid cursor") from None


def _check_types(values: list[str] | None, allowed: tuple[str, ...], what: str) -> None:
    if values and (bad := [v for v in values if v not in allowed]):
        raise HTTPException(400, f"Unknown {what}: {', '.join(bad)}")


def _entity(row: EntityRow) -> EntityFeedItem:
    e = row.entity
    return EntityFeedItem(
        id=e.id,
        stix_id=e.stix_id,
        type=e.type,
        name=e.name,
        aliases=sorted({a.alias for a in e.aliases}),
        description=e.description,
        external_id=e.external_id,
        identity_class=e.identity_class,
        source=e.source,
        tlp=e.tlp,
        suppressed=e.suppressed,
        merged_into_stix_id=row.merged_into_stix_id,
        revoked=e.suppressed or e.merged_into_id is not None,
        first_seen=e.first_seen,
        last_seen=e.last_seen,
        created_at=e.created_at,
        changed_at=e.feed_changed_at,
    )


def _relationship(row: RelationshipRow) -> RelationshipFeedItem:
    r = row.relationship
    return RelationshipFeedItem(
        id=r.id,
        stix_id=r.stix_id,
        relationship_type=r.relationship_type,
        source_ref=row.source_ref,
        target_ref=row.target_ref,
        confidence=r.confidence,
        first_seen=r.first_seen,
        last_seen=r.last_seen,
        provenance=r.provenance,
        description=r.description,
        tlp=r.tlp,
        revoked=r.revoked_at is not None,
        revoked_at=r.revoked_at,
        created_at=r.created_at,
        changed_at=r.feed_changed_at,
    )


@router.get("/entities", response_model=EntityFeedPage)
async def list_entities(
    type_: list[str] | None = Query(None, alias="type"),
    changed_after: datetime.datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    _principal: MachinePrincipal = Depends(require_token("intel:read")),
    session: AsyncSession = Depends(get_db),
) -> EntityFeedPage:
    _check_types(type_, ENTITY_TYPES, "type")
    after = _common(changed_after, cursor)
    page = await entity_feed_page(
        session,
        max_tlp=_principal.max_tlp,
        limit=limit,
        types=type_,
        changed_after=changed_after,
        after=after,
    )
    return EntityFeedPage(items=[_entity(r) for r in page.items], next_cursor=page.next_cursor)


@router.get("/relationships", response_model=RelationshipFeedPage)
async def list_relationships(
    type_: list[str] | None = Query(None, alias="type"),
    changed_after: datetime.datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    _principal: MachinePrincipal = Depends(require_token("intel:read")),
    session: AsyncSession = Depends(get_db),
) -> RelationshipFeedPage:
    _check_types(type_, RELATIONSHIP_TYPES, "type")
    after = _common(changed_after, cursor)
    page = await relationship_feed_page(
        session,
        max_tlp=_principal.max_tlp,
        limit=limit,
        types=type_,
        changed_after=changed_after,
        after=after,
    )
    return RelationshipFeedPage(
        items=[_relationship(r) for r in page.items], next_cursor=page.next_cursor
    )
