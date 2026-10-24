"""`llm_calls` -- log ringan setiap panggilan LLM (satu baris per panggilan, bukan per percobaan
retry di dalam SDK).

Hanya metadata: tidak ada prompt maupun respons (isinya bisa memuat teks artikel/CVE). Dipakai
kartu LLM di /data-health (status terakhir, error terakhir, penggunaan per task) dan dibersihkan
setelah 90 hari. `task` dan `status` divalidasi di aplikasi, tanpa CHECK (seperti
`daily_recaps.kind`); `status` = `ok` | `empty` | `error`.
"""

from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base


class LlmCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_at", "at"),
        Index("ix_llm_calls_task_at", "task", "at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    task: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    """8 hex pertama sha256 dari system prompt; NULL kalau task tidak punya prompt tunggal."""
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(80))
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    """Token NULL = provider tidak melaporkan usage (jangan dihitung sebagai 0)."""
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
