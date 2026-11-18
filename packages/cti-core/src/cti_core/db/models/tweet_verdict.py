"""`tweet_verdicts` -- catatan tiap klasifikasi tweet (juga yang ditolak).

Tabel `tweets` hanya menyimpan tweet yang lolos, jadi tanpa tabel ini label negatif hilang.
Baris `source='llm'` jadi bahan latih model relevansi tweet; baris `gate` (diputuskan model
lokal tanpa LLM) hanya jejak audit dan tidak boleh dipakai melatih (menghindari umpan balik).
Dibersihkan mingguan oleh `run_training` (retensi 90 hari).
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base

VERDICT_SOURCES = ("llm", "gate")


class TweetVerdict(Base):
    __tablename__ = "tweet_verdicts"
    __table_args__ = (CheckConstraint("source IN ('llm', 'gate')", name="source_valid"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tweet_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    related_cyber: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    """`llm` (label dari model bahasa) / `gate` (diputuskan model lokal)."""
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    relevance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
