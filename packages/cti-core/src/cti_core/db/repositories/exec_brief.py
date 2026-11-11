"""Repo `exec_briefs` (async; pemakainya API Exec dan task brief harian lewat `asyncio.run`)."""

from __future__ import annotations

import datetime
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.db.models.exec_brief import ExecBrief


class AsyncExecBriefRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, brief_date: datetime.date) -> ExecBrief | None:
        stmt = select(ExecBrief).where(ExecBrief.brief_date == brief_date)
        return (await self.session.scalars(stmt)).first()

    async def latest(self, *, since: datetime.date) -> ExecBrief | None:
        """Brief terbaru dengan `brief_date >= since` (batas bawah inklusif)."""
        stmt = (
            select(ExecBrief)
            .where(ExecBrief.brief_date >= since)
            .order_by(ExecBrief.brief_date.desc())
            .limit(1)
        )
        return (await self.session.scalars(stmt)).first()

    async def list_dates(self, *, since: datetime.date) -> list[datetime.date]:
        """Tanggal brief yang tersedia, terbaru dulu."""
        stmt = (
            select(ExecBrief.brief_date)
            .where(ExecBrief.brief_date >= since)
            .order_by(ExecBrief.brief_date.desc())
        )
        return list(await self.session.scalars(stmt))

    async def upsert(
        self,
        *,
        brief_date: datetime.date,
        markdown: str,
        filters: dict[str, Any],
        generated_by: str,
        model: str,
        prompt_version: str | None,
        replace: bool,
    ) -> ExecBrief | None:
        """Simpan brief satu tanggal. `replace=False` (scheduler) tidak menimpa brief yang sudah
        ada dan mengembalikan None, supaya dua proses yang berebut tidak saling timpa;
        `replace=True` (regenerate manual) menimpa dan memperbarui `generated_at`."""
        values = {
            "markdown": markdown,
            "filters": filters,
            "generated_by": generated_by,
            "model": model,
            "prompt_version": prompt_version,
        }
        stmt = pg_insert(ExecBrief).values(brief_date=brief_date, **values)
        if replace:
            stmt = stmt.on_conflict_do_update(
                constraint="uq_exec_briefs_brief_date",
                set_={**values, "generated_at": func.now()},
            )
        else:
            stmt = stmt.on_conflict_do_nothing()
        result = await self.session.scalars(
            stmt.returning(ExecBrief), execution_options={"populate_existing": True}
        )
        return result.first()

    async def purge_before(self, cutoff: datetime.date) -> int:
        """Hapus brief dengan `brief_date < cutoff`; return jumlah baris."""
        result = await self.session.execute(delete(ExecBrief).where(ExecBrief.brief_date < cutoff))
        return cast(CursorResult[Any], result).rowcount
