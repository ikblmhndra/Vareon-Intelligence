"""AsyncRecapRepo -- CRUD cache `daily_recaps`. Fase 7.3 (router `recap`,
Bagian 5). Generate-nya sendiri (kumpulin data + panggil LLM) ada di
`cti_api.services.recap`, repo ini murni persistensi.

Tabel ini menyimpan dua jenis baris (`kind` = `daily` | `weekly`, #21) yang boleh berbagi `date`
(Senin yang sama), jadi `get`/`upsert` SELALU menyebut `kind`. Dulu `get(date)` memakai
`scalar_one_or_none()` tanpa `kind`: begitu satu hari punya dua baris, itu `MultipleResultsFound`
(HTTP 500)."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.db.models.recap import DailyRecap


class AsyncRecapRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, date: str, kind: str = "daily") -> DailyRecap | None:
        result = await self.session.execute(
            select(DailyRecap).where(DailyRecap.date == date, DailyRecap.kind == kind)
        )
        return result.scalar_one_or_none()

    async def get_latest(self, kind: str) -> DailyRecap | None:
        """Baris `kind` dengan `date` terbaru (recap mingguan terakhir yang tersimpan)."""
        result = await self.session.execute(
            select(DailyRecap)
            .where(DailyRecap.kind == kind)
            .order_by(DailyRecap.date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, recap_id: int, *, for_update: bool = False) -> DailyRecap | None:
        """`for_update`: kunci barisnya sampai transaksi selesai. Override scorecard membaca
        `quality`, mengubah satu entri, lalu menulis seluruh JSONB; dua analis yang menimpa event
        berbeda di saat yang sama akan saling menghapus kalau tidak diserialkan."""
        stmt = select(DailyRecap).where(DailyRecap.id == recap_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_latest(self, kind: str, limit: int) -> list[DailyRecap]:
        """Baris `kind` dengan `date` terbaru dulu, paling banyak `limit` (hit rate scorecard:
        8 recap mingguan terakhir)."""
        result = await self.session.execute(
            select(DailyRecap)
            .where(DailyRecap.kind == kind)
            .order_by(DailyRecap.date.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_overlapping(
        self, kind: str, start: datetime.date, end: datetime.date
    ) -> list[DailyRecap]:
        """Baris `kind` yang rentangnya beririsan dengan `[start, end]` (kedua ujung inklusif),
        urut `period_start`. Pekan yang hanya menyentuh satu hari jendela ikut: Executive Summary
        newsletter memakai semua pekan yang menyentuh bulannya. Baris tanpa periode (kolom
        nullable, baris sebelum kolomnya ada) tidak pernah beririsan."""
        result = await self.session.execute(
            select(DailyRecap)
            .where(
                DailyRecap.kind == kind,
                DailyRecap.period_start <= end,
                DailyRecap.period_end >= start,
            )
            .order_by(DailyRecap.period_start)
        )
        return list(result.scalars().all())

    async def list_recent(self, limit: int = 30) -> list[DailyRecap]:
        """Kedua jenis, `date` terbaru dulu; pada `date` yang sama yang mingguan di atas."""
        result = await self.session.execute(
            select(DailyRecap).order_by(DailyRecap.date.desc(), DailyRecap.kind.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def upsert(self, date: str, *, kind: str = "daily", **fields: Any) -> DailyRecap:
        existing = await self.get(date, kind)
        if existing is not None:
            for k, v in fields.items():
                setattr(existing, k, v)
            await self.session.flush()
            return existing
        row = DailyRecap(date=date, kind=kind, **fields)
        self.session.add(row)
        await self.session.flush()
        return row
