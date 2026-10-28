"""`relevance_models` -- model relevansi lokal hasil latih (P5) + status gate bersama.

Satu baris `active` paling banyak (indeks unik parsial). `gate_state` hidup di baris model
supaya semua worker membaca keputusan gate yang sama dan model baru mewarisinya. Lihat
`docs/superpowers/specs/2026-10-25-p5-relevance-model-design.md` bagian 7.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base, TimestampMixin


class RelevanceModel(TimestampMixin, Base):
    __tablename__ = "relevance_models"
    __table_args__ = (
        Index(
            "uq_relevance_models_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    """`active` / `retired` / `rejected`; divalidasi di repo, bukan CHECK (seperti
    `ArticleCountry.role`)."""
    artifact: Mapped[bytes | None] = mapped_column(LargeBinary)
    """Pipeline sklearn hasil `joblib` tanpa embedder; NULL untuk run `rejected`."""
    feature_version: Mapped[str] = mapped_column(String(200), nullable=False)
    """Nama+revisi model embedding dan versi fastembed/scikit-learn; beda dengan runtime =
    model tidak dipakai (fallback LLM) dan memicu latih ulang."""
    n_examples: Mapped[int] = mapped_column(Integer, nullable=False)
    class_counts: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    gate_state: Mapped[str] = mapped_column(
        String(10), nullable=False, default="shadow", server_default=text("'shadow'")
    )
    """`shadow` / `gate`."""
    gate_changed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    """Alasan run ditolak."""
