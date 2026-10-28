"""Indicator (dulu IOC) -- gantiin `news_db.iocs`. Ditulis DUA sisi di sistem lama (scraper
lewat `dbMongo.upsert_ioc_from_feed`, web lewat `ioc_service.upsert_ioc`)
tanpa koordinasi -- lihat plan §1 tabel kolaborasi. Di sini cuma ada SATU
tabel, SATU cara nulis (lewat IndicatorRepo, Fase 2.8).
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cti_core.db.base import Base, TimestampMixin


class Indicator(TimestampMixin, Base):
    __tablename__ = "indicators"
    __table_args__ = (UniqueConstraint("type", "value", name="uq_indicators_type_value"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    """ip | url | domain | email | sha256 | sha1 | md5 | cve -- lihat
    cti_enrich.ioc (Fase 5), yang jadi SATU-SATUNYA ekstraktor (gantiin
    4 salinan iocExtractor.py yang dicatat di plan §6)."""
    value: Mapped[str] = mapped_column(Text, nullable=False)

    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    seen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    confidence_score: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=50)
    confidence_decayed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    actionability_score: Mapped[int | None] = mapped_column(SmallInteger)
    """0-100, dihitung `confidence_service.compute_ioc_actionability()` --
    cuma keisi pas ada feedback (`submit_feedback`), null kalau belum
    pernah dihitung. Fase 7.4 Grup D."""
    actionability_label: Mapped[str | None] = mapped_column(String(20))
    """block_now | investigate | monitor | archive."""
    recommended_action: Mapped[str | None] = mapped_column(Text)

    tp_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fp_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    auto_suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suppression_reason: Mapped[str | None] = mapped_column(Text)

    enrichment: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """Payload enrichment provider (mis. hasil lookup OTX/AbuseIPDB) --
    lihat enrichmentTemplate.py di repo lama. Cair, gak dinormalisasi."""

    sources: Mapped[list[IndicatorSource]] = relationship(
        back_populates="indicator", cascade="all, delete-orphan", lazy="selectin"
    )
    tags: Mapped[list[IndicatorTag]] = relationship(
        back_populates="indicator", cascade="all, delete-orphan", lazy="selectin"
    )
    threat_actors: Mapped[list[IndicatorThreatActor]] = relationship(
        back_populates="indicator", cascade="all, delete-orphan", lazy="selectin"
    )
    feedback: Mapped[list[IndicatorFeedback]] = relationship(
        back_populates="indicator", cascade="all, delete-orphan", lazy="selectin"
    )


class IndicatorSource(Base):
    """Ganti array `sources[]` -- di URL/artikel mana IOC ini kelihatan."""

    __tablename__ = "indicator_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    indicator_id: Mapped[int] = mapped_column(
        ForeignKey("indicators.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    context: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    indicator: Mapped[Indicator] = relationship(back_populates="sources")


class IndicatorTag(Base):
    __tablename__ = "indicator_tags"
    __table_args__ = (UniqueConstraint("indicator_id", "tag", name="uq_indicator_tag"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    indicator_id: Mapped[int] = mapped_column(
        ForeignKey("indicators.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    indicator: Mapped[Indicator] = relationship(back_populates="tags")


class IndicatorThreatActor(Base):
    __tablename__ = "indicator_threat_actors"
    __table_args__ = (
        UniqueConstraint("indicator_id", "threat_actor", name="uq_indicator_threat_actor"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    indicator_id: Mapped[int] = mapped_column(
        ForeignKey("indicators.id", ondelete="CASCADE"), nullable=False
    )
    threat_actor: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    indicator: Mapped[Indicator] = relationship(back_populates="threat_actors")


class IndicatorFeedback(Base):
    """Ganti array `feedback_log[]` -- riwayat TP/FP dari analis."""

    __tablename__ = "indicator_feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    indicator_id: Mapped[int] = mapped_column(
        ForeignKey("indicators.id", ondelete="CASCADE"), nullable=False
    )
    verdict: Mapped[str] = mapped_column(String(2), nullable=False)
    """"tp" | "fp"."""
    submitted_by: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    indicator: Mapped[Indicator] = relationship(back_populates="feedback")
