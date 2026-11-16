"""`exec_briefs` -- brief eksekutif harian, satu dokumen bersama per tanggal.

Brief dibuat otomatis tiap pagi (worker `exec.brief_daily`, 06:00 Jakarta) dan bisa dibuat ulang
manual lewat `POST /api/exec/brief`. Isinya ringkasan lintas-klien (platform-wide), jadi sengaja
TANPA `client_id`: semua klien membaca dokumen yang sama dan tanggal yang sama tidak pernah
punya dua versi (unique `brief_date`). `brief_date` adalah tanggal kalender Asia/Jakarta.

Retensi 30 hari: worker membuang baris yang lebih tua lewat `purge_before`, jadi tabel paling
banyak berisi ~31 baris dan unique index sudah cukup melayani semua pencarian (tanpa index lain).
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base


class ExecBrief(Base):
    __tablename__ = "exec_briefs"
    __table_args__ = (UniqueConstraint("brief_date", name="uq_exec_briefs_brief_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    brief_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    """Jawaban model apa adanya."""
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """`{"days": int, "incident_only": bool, "confirmed_only": bool}` yang dipakai saat membuat."""
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    """Diisi ulang saat brief diganti (`replace=True`)."""
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    """`scheduler` atau `users.username`."""
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(16))
