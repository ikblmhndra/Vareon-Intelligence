"""Skema API entitas P7c (`/api/entities`, `/api/relationships`, spec 5.2)."""

from __future__ import annotations

import datetime
from typing import Annotated, Any

from cti_core.entity import ENTITY_TYPES, RELATIONSHIP_TYPES
from pydantic import BaseModel, Field, field_validator, model_validator


class EntityRef(BaseModel):
    id: int
    type: str
    name: str
    external_id: str | None = None


class AliasOut(BaseModel):
    id: int
    alias: str
    source: str


class EntityListItem(BaseModel):
    id: int
    type: str
    name: str
    aliases: list[str]
    external_id: str | None
    source: str
    suppressed: bool
    mentions_30d: int
    mentions_90d: int
    last_seen: datetime.datetime | None
    watched: bool
    first_seen: datetime.datetime | None = None


class EntityListResponse(BaseModel):
    items: list[EntityListItem]
    next_cursor: str | None
    total: int | None = None
    """Jumlah baris filter yang sama; hanya di halaman pertama (tanpa kursor), lalu None."""


class EntityDetail(BaseModel):
    id: int
    type: str
    name: str
    external_id: str | None
    source: str
    suppressed: bool
    mentions_30d: int
    mentions_90d: int
    last_seen: datetime.datetime | None
    watched: bool
    stix_id: str
    description: str | None
    identity_class: str | None
    merged_into_id: int | None
    """Terisi = tombstone; web mengalihkan ke entitas ini."""
    first_seen: datetime.datetime | None
    aliases: list[AliasOut]
    profile: dict[str, Any] | None = None
    """Profil LLM tersimpan (hanya aktor), dibuat lewat `POST /api/entities/{id}/profile`."""
    profile_generated_at: datetime.datetime | None = None
    merged_from: list[EntityRef] = []
    """Tombstone yang `merged_into_id`-nya entitas ini, merge terbaru dulu. Dialog split
    memakainya untuk tahu alias nama-sendiri mana yang menghidupkan tombstone mana."""


class EntityCreate(BaseModel):
    type: str
    name: str = Field(min_length=1, max_length=300)
    aliases: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(default_factory=list)
    description: str | None = None
    external_id: str | None = Field(default=None, max_length=50)
    """Wajib untuk `attack-pattern` (id teknik, Ruling 7)."""
    identity_class: str | None = None

    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in ENTITY_TYPES:
            raise ValueError(f"type must be one of {', '.join(ENTITY_TYPES)}")
        return v

    @model_validator(mode="after")
    def _technique_id(self) -> EntityCreate:
        if self.type == "attack-pattern" and not (self.external_id or "").strip():
            raise ValueError("attack-pattern needs external_id (technique id)")
        if self.type == "attack-pattern" and self.aliases:
            raise ValueError("attack-pattern aliases are the technique id only")
        if self.identity_class not in (None, "class", "organization"):
            raise ValueError("identity_class must be 'class' or 'organization'")
        if self.identity_class is not None and self.type != "identity":
            raise ValueError("identity_class is only for type 'identity'")
        return self


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    suppressed: bool | None = None


class AliasCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=300)


class MergeBody(BaseModel):
    into_id: int


class SplitBody(BaseModel):
    alias_ids: list[int] = Field(min_length=1)


class MergeResultOut(BaseModel):
    moved_aliases: int
    moved_mentions: int
    moved_relationships: int
    moved_watches: int
    moved_profile: bool


class RelationshipOut(BaseModel):
    id: int
    stix_id: str
    relationship_type: str
    source: EntityRef | None
    """None bila sumbernya indikator (`indicator indicates X`)."""
    source_indicator_id: int | None
    target: EntityRef
    confidence: int | None
    provenance: str
    description: str | None
    first_seen: datetime.datetime | None
    last_seen: datetime.datetime | None
    created_by: str | None
    revoked_at: datetime.datetime | None
    revoked_by: str | None


class CoMention(BaseModel):
    entity: EntityRef
    stories: int


class EntityRelationshipsResponse(BaseModel):
    relationships: list[RelationshipOut]
    co_mentions: list[CoMention]


class RelationshipCreate(BaseModel):
    source_id: int
    relationship_type: str
    target_id: int
    confidence: int = Field(default=75, ge=0, le=100)
    description: str | None = None

    @field_validator("relationship_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in RELATIONSHIP_TYPES:
            raise ValueError(f"relationship_type must be one of {', '.join(RELATIONSHIP_TYPES)}")
        return v

    @model_validator(mode="after")
    def _distinct_ends(self) -> RelationshipCreate:
        if self.source_id == self.target_id:
            raise ValueError("source_id and target_id must differ")
        return self


class WatchOut(BaseModel):
    watched: bool


class EntityProfileOut(BaseModel):
    profile: dict[str, Any]


class EntityStoryItem(BaseModel):
    id: int
    title: str
    lead_source: str
    article_count: int
    source_count: int
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    mentioned_articles: int
    """Anggota story yang menyebut entitas ini."""


class EntityStoriesResponse(BaseModel):
    items: list[EntityStoryItem]
    total: int


class EntityIndicatorItem(BaseModel):
    id: int
    type: str
    value: str
    confidence_score: int
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    revoked_at: datetime.datetime | None


class EntityIndicatorsResponse(BaseModel):
    items: list[EntityIndicatorItem]
    total: int


class EntityCveItem(BaseModel):
    id: int
    cve_id: str
    tech: str | None
    cve_score: float | None
    cve_severity: str | None
    cisa_kev: bool
    published: datetime.date | None
    detected_on: datetime.datetime


class EntityCvesResponse(BaseModel):
    items: list[EntityCveItem]
    total: int


class TimelineMonth(BaseModel):
    month: str
    """`YYYY-MM`."""
    articles: int


class EntityTimelineResponse(BaseModel):
    months: list[TimelineMonth]


class AttackTechniqueOut(EntityRef):
    tactics: list[str]


class AttackMitigationOut(BaseModel):
    mitigation_id: str
    name: str
    description: str
    techniques: list[str]
    """Id teknik entitas ini yang dimitigasi."""


class EntityAttackResponse(BaseModel):
    techniques: list[AttackTechniqueOut]
    mitigations: list[AttackMitigationOut]
    layer: dict[str, Any]
    """Layer ATT&CK Navigator (JSON siap impor)."""
