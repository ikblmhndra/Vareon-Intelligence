"""Skema feed mesin REST (P7b 4.3). Urutan field = urutan kolom CSV."""

import datetime

from pydantic import BaseModel


class IndicatorFeedItem(BaseModel):
    id: int
    stix_id: str
    type: str
    value: str
    state: str
    valid_from: datetime.datetime
    valid_until: datetime.datetime | None
    first_seen: datetime.datetime
    last_seen: datetime.datetime
    seen_count: int
    confidence: int
    tlp: str
    pap: str
    tags: list[str]
    revoked_at: datetime.datetime | None
    changed_at: datetime.datetime


class IndicatorFeedPage(BaseModel):
    items: list[IndicatorFeedItem]
    next_cursor: str | None


class EntityFeedItem(BaseModel):
    """Satu entitas feed REST `/api/v2/entities` (P7c spec 5.3). `revoked` = suppressed atau
    tombstone merge (`merged_into_stix_id` menunjuk entitas tujuan)."""

    id: int
    stix_id: str
    type: str
    name: str
    aliases: list[str]
    description: str | None
    external_id: str | None
    identity_class: str | None
    source: str
    tlp: str
    suppressed: bool
    merged_into_stix_id: str | None
    revoked: bool
    first_seen: datetime.datetime | None
    last_seen: datetime.datetime | None
    created_at: datetime.datetime
    changed_at: datetime.datetime


class EntityFeedPage(BaseModel):
    items: list[EntityFeedItem]
    next_cursor: str | None


class RelationshipFeedItem(BaseModel):
    """Satu relasi feed REST `/api/v2/relationships`; `source_ref`/`target_ref` = id STIX ujung
    (entitas, atau indikator untuk sumber `indicates`)."""

    id: int
    stix_id: str
    relationship_type: str
    source_ref: str
    target_ref: str
    confidence: int | None
    first_seen: datetime.datetime | None
    last_seen: datetime.datetime | None
    provenance: str
    description: str | None
    tlp: str
    revoked: bool
    revoked_at: datetime.datetime | None
    created_at: datetime.datetime
    changed_at: datetime.datetime


class RelationshipFeedPage(BaseModel):
    items: list[RelationshipFeedItem]
    next_cursor: str | None
