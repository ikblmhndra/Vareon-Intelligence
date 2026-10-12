"""Recap harian/mingguan -- gantiin `daily_recaps` (Mongo). Fase 7.3 (router
`recap`, Bagian 5). Ringkasan LLM (news+X intel dalam satu periode) + forecast
ke depan, cached per `(kind, date)`.

`yesterday`/`forecast`/`counts`/`token_usage` JSONB -- output LLM
terstruktur + metadata pemanggilan, "cair" persis alasan yang sama kayak
`Newsletter.sections`/`PIRRequirement.criteria` (bag hasil LLM/ad hoc,
bukan entitas relasional yang perlu di-query per field).

**Dua jenis baris (#21, 2026-10-11).** `kind='weekly'`: recap terjadwal satu pekan Senin-Minggu
(tanggal UTC), `date` = Senin pekan itu, `period_start` = Senin, `period_end` = Minggu.
`kind='daily'`: recap satu hari yang dipicu tangan (`date` = harinya, kedua periode = `date`).
Nama tabel dan kolom JSONB `yesterday`/`forecast` tidak diganti (mengganti nama tidak sebanding
dengan ributnya): isi recap mingguan masuk ke `yesterday` juga, artinya "isi recap" apa pun
periodenya."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base


class DailyRecap(Base):
    __tablename__ = "daily_recaps"
    __table_args__ = (UniqueConstraint("kind", "date", name="uq_daily_recap_kind_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(
        String(10), nullable=False, default="daily", server_default="daily"
    )
    """`daily` | `weekly` (dicek di aplikasi, bukan CHECK Postgres, biar nilai baru tidak butuh
    migrasi). Recap mingguan dan harian boleh berbagi `date` (Senin yang sama), makanya unik di
    `(kind, date)` dan SEMUA pembacaan harus menyebut `kind`."""
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    """`YYYY-MM-DD` -- string, bukan `Date`, konsisten sama gimana
    `recap_service.py` lama nge-treat tanggal ini di mana-mana (kunci
    lookup `daily_recaps`, bukan field yang di-range-query). Recap mingguan: hari Senin."""
    period_start: Mapped[datetime.date | None] = mapped_column(Date)
    period_end: Mapped[datetime.date | None] = mapped_column(Date)
    """Rentang yang dirangkum, inklusif. NULLABLE (bukan NOT NULL) supaya kode lama tetap bisa
    INSERT saat rollback/deploy bergulir; migrasi mengisi baris lama, pembaca jatuh ke `date`."""
    headline: Mapped[str] = mapped_column(Text, nullable=False, default="")
    yesterday: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    forecast: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    raw_llm: Mapped[str | None] = mapped_column(Text)
    """Diisi cuma kalau parsing JSON dari LLM gagal (`_extract_json`
    fallback `{"_raw": raw}`) -- port apa adanya, audit trail buat
    kegagalan parsing, `None` di jalur normal."""
