"""Model entitas P7c (STIX SDO/SRO): `entities`, `entity_aliases`, `relationships`,
`entity_mentions`, `entity_watches`, `entity_profiles`, `reference_snapshots`.

Menggantikan tabel link per-tipe (`article_threat_actors`, `article_ttps`, ...). Trigger
`entity_aliases_sync_type` (denormalisasi `entity_type`) dan tabel jam feed hidup di migrasi
`entity_model`; autogenerate tidak membandingkan trigger.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CHAR, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cti_core.db.base import Base, TimestampMixin


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


_TLP = ("clear", "green", "amber", "amber+strict", "red")
_TYPES = (
    "intrusion-set", "malware", "tool", "attack-pattern",
    "vulnerability", "campaign", "identity", "location",
)  # fmt: skip
_ENTITY_SOURCES = (
    "attack", "galaxy", "dictionary", "analyst", "cve", "iso", "sector", "ransomware", "legacy",
)  # fmt: skip
_ALIAS_SOURCES = ("attack", "galaxy", "analyst", "legacy", "dictionary")
_REL_TYPES = (
    "uses", "targets", "attributed-to", "exploits", "indicates",
    "variant-of", "located-at", "related-to", "subtechnique-of",
)  # fmt: skip
_REL_PROVENANCE = ("attack", "analyst", "ransomware")
_METHODS = ("dictionary", "llm", "keyword", "explicit", "analyst", "legacy")


class Entity(TimestampMixin, Base):
    __tablename__ = "entities"
    __table_args__ = (
        CheckConstraint(_in("type", _TYPES), name="type"),
        CheckConstraint(_in("source", _ENTITY_SOURCES), name="source"),
        CheckConstraint(_in("tlp", _TLP), name="tlp"),
        Index(
            "uq_entities_type_lower_name",
            "type",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("merged_into_id IS NULL AND type <> 'attack-pattern'"),
        ),
        # identitas teknik = id teknik (nama ATT&CK tidak unik: sub-teknik, lintas domain)
        Index(
            "uq_entities_type_external_id",
            "type",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL AND merged_into_id IS NULL"),
        ),
        Index("ix_entities_feed_changed_at_id", "feed_changed_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    stix_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    """Objek ATT&CK memakai `stix_id` ATT&CK; lainnya dihitung sekali saat dibuat."""
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(50))
    identity_class: Mapped[str | None] = mapped_column(String(20))
    """`class` (sektor) atau `organization` (korban); hanya untuk tipe `identity`."""
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    suppressed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    """Menggantikan `ta_whitelist`: tak pernah dicocokkan, disembunyikan, terbit sebagai revoked."""
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"))
    """Tombstone sesudah merge."""
    first_seen: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    tlp: Mapped[str] = mapped_column(String(12), nullable=False, server_default="clear")
    feed_changed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    """Jam feed mesin: `trg_entities_feed_bump` (name, description, external_id, suppressed,
    merged_into_id, tlp) dan `trg_entity_aliases_feed_bump` (alias masuk/keluar), migrasi
    `entity_model`. first_seen/last_seen tidak membump."""

    aliases: Mapped[list[EntityAlias]] = relationship(
        back_populates="entity", lazy="selectin", cascade="all, delete-orphan"
    )


class EntityAlias(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        CheckConstraint(_in("source", _ALIAS_SOURCES), name="source"),
        UniqueConstraint("entity_type", "alias_norm", name="uq_entity_aliases_type_norm"),
        Index("ix_entity_aliases_entity_id", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    """Denormalisasi `entities.type`; diisi TRIGGER `entity_aliases_sync_type` (nilai kiriman
    ditimpa), jadi keunikan `(entity_type, alias_norm)` tak bisa dilewati SQL mentah."""
    alias: Mapped[str] = mapped_column(String(300), nullable=False)
    alias_norm: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    entity: Mapped[Entity] = relationship(back_populates="aliases")


class Relationship(TimestampMixin, Base):
    __tablename__ = "relationships"
    __table_args__ = (
        CheckConstraint(_in("relationship_type", _REL_TYPES), name="relationship_type"),
        CheckConstraint(_in("provenance", _REL_PROVENANCE), name="provenance"),
        CheckConstraint(_in("tlp", _TLP), name="tlp"),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="confidence"),
        CheckConstraint("num_nonnulls(source_entity_id, source_indicator_id) = 1", name="source"),
        Index(
            "uq_relationships_edge",
            text("coalesce(source_entity_id, 0)"),
            text("coalesce(source_indicator_id, 0)"),
            "relationship_type",
            "target_entity_id",
            unique=True,
        ),
        Index("ix_relationships_source_entity_id", "source_entity_id"),
        Index("ix_relationships_target_entity_id", "target_entity_id"),
        Index("ix_relationships_feed_changed_at_id", "feed_changed_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stix_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    relationship_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_entity_id: Mapped[int | None] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE")
    )
    source_indicator_id: Mapped[int | None] = mapped_column(
        ForeignKey("indicators.id", ondelete="CASCADE")
    )
    target_entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    first_seen: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(200))
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(String(200))
    tlp: Mapped[str] = mapped_column(String(12), nullable=False, server_default="clear")
    feed_changed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    """Jam feed mesin: `trg_relationships_feed_bump` (tipe, ujung, confidence, description,
    revoked_at, tlp), migrasi `entity_model`."""


class EntityMention(Base):
    __tablename__ = "entity_mentions"
    __table_args__ = (
        CheckConstraint(_in("method", _METHODS), name="method"),
        CheckConstraint(
            "num_nonnulls(article_id, indicator_id, cve_tracker_id) = 1", name="subject"
        ),
        UniqueConstraint(
            "article_id",
            "indicator_id",
            "cve_tracker_id",
            "entity_id",
            "role",
            name="uq_entity_mentions_subject_entity_role",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_entity_mentions_entity_id_article_id", "entity_id", "article_id"),
        Index("ix_entity_mentions_article_id", "article_id"),
        Index("ix_entity_mentions_indicator_id", "indicator_id"),
        Index("ix_entity_mentions_cve_tracker_id", "cve_tracker_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    indicator_id: Mapped[int | None] = mapped_column(
        ForeignKey("indicators.id", ondelete="CASCADE")
    )
    cve_tracker_id: Mapped[int | None] = mapped_column(
        ForeignKey("cve_tracker.id", ondelete="CASCADE")
    )
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), nullable=False)
    method: Mapped[str] = mapped_column(String(12), nullable=False)
    matched_alias: Mapped[str] = mapped_column(String(300), nullable=False)
    """Bentuk teks yang menghasilkan mention; membuat split entitas eksak."""
    role: Mapped[str | None] = mapped_column(String(10))
    evidence: Mapped[str | None] = mapped_column(Text)
    extracted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    entity: Mapped[Entity] = relationship(lazy="joined")


class EntityWatch(Base):
    __tablename__ = "entity_watches"
    __table_args__ = (UniqueConstraint("client_id", "entity_id", name="uq_entity_watches_pair"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EntityProfile(Base):
    __tablename__ = "entity_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), unique=True
    )
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReferenceSnapshot(Base):
    __tablename__ = "reference_snapshots"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    content: Mapped[Any] = mapped_column(JSONB, nullable=False)
