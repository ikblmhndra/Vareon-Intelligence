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
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    and_,
    case,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cti_core.db.base import Base, TimestampMixin


class Indicator(TimestampMixin, Base):
    __tablename__ = "indicators"
    __table_args__ = (
        UniqueConstraint("type", "value", name="uq_indicators_type_value"),
        CheckConstraint("tlp IN ('clear', 'green', 'amber', 'amber+strict', 'red')", name="tlp"),
        CheckConstraint("pap IN ('clear', 'green', 'amber', 'red')", name="pap"),
    )

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

    valid_from: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    """Awal masa berlaku; diisi dari `first_seen_at` oleh migrasi dan tidak berubah sesudahnya."""
    valid_until: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    """`last_seen_at` + TTL tipe (cti_core.indicator.validity); `NULL` = tidak kedaluwarsa."""
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    """Diisi saat analis menandai FP; final, tidak dihapus oleh ingest."""
    revoked_by: Mapped[str | None] = mapped_column(String(200))
    tlp: Mapped[str] = mapped_column(String(12), nullable=False, server_default="clear")
    """TLP 2.0: clear | green | amber | amber+strict | red."""
    pap: Mapped[str] = mapped_column(String(8), nullable=False, server_default="clear")
    """PAP: clear | green | amber | red."""

    enrichment: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """Payload enrichment provider (mis. hasil lookup OTX/AbuseIPDB) --
    lihat enrichmentTemplate.py di repo lama. Cair, gak dinormalisasi."""

    @hybrid_property
    def state(self) -> str:
        """revoked > allowlisted > expired > active. Dihitung, bukan disimpan: kedaluwarsa terjadi
        karena waktu berlalu, jadi kolom tersimpan butuh sweep dan bisa basi."""
        if self.revoked_at is not None:
            return "revoked"
        if self.auto_suppressed:
            return "allowlisted"
        if self.valid_until is not None and self.valid_until < datetime.datetime.now(datetime.UTC):
            return "expired"
        return "active"

    @state.inplace.expression
    @classmethod
    def _state_expression(cls) -> Any:
        return case(
            (cls.revoked_at.is_not(None), "revoked"),
            (cls.auto_suppressed.is_(True), "allowlisted"),
            (cls.valid_until < func.now(), "expired"),  # NULL < now() bukan true: tak kedaluwarsa
            else_="active",
        )

    @hybrid_property
    def usable(self) -> bool:
        """Dipakai konsumen bila tidak di-allowlist dan tidak dicabut; kedaluwarsa tetap boleh."""
        return not self.auto_suppressed and self.revoked_at is None

    @usable.inplace.expression
    @classmethod
    def _usable_expression(cls) -> Any:
        return and_(cls.auto_suppressed.is_(False), cls.revoked_at.is_(None))

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
