"""Hunting packs (P7e): `sigma_rules` (aturan SigmaHQ yang dimuat) dan `hunt_hypotheses`
(draf hipotesis hunting dari LLM per story/entitas).

`hunt_hypotheses` tanpa FK karena anchor menunjuk dua tabel (`stories`/`entities`); baris yatim
(story dihapus, entitas di-merge) tidak pernah dibaca. Regenerate menimpa baris yang sama.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base


class SigmaRule(Base):
    __tablename__ = "sigma_rules"
    __table_args__ = (Index("ix_sigma_rules_techniques", "techniques", postgresql_using="gin"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    """Verbatim, atribusi DRL."""
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    ruleset: Mapped[str] = mapped_column(String(20), nullable=False)
    """`core` atau `emerging-threats` (dari path)."""
    logsource: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    techniques: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False)
    """ID ATT&CK huruf besar dari `tags` (`attack.t1059.001` -> `T1059.001`)."""
    path: Mapped[str] = mapped_column(Text, nullable=False)
    release: Mapped[str] = mapped_column(String(40), nullable=False)
    yaml: Mapped[str] = mapped_column(Text, nullable=False)
    loaded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HuntHypothesis(Base):
    __tablename__ = "hunt_hypotheses"
    __table_args__ = (
        CheckConstraint("anchor_type IN ('story', 'entity')", name="anchor_type"),
        UniqueConstraint("anchor_type", "anchor_id", name="uq_hunt_hypotheses_anchor"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    anchor_type: Mapped[str] = mapped_column(String(10), nullable=False)
    anchor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
