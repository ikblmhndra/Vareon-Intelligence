"""Repo `llm_calls`: tulis sync (klien LLM di Celery/CLI), baca async (API /data-health)."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.models.llm_call import LlmCall


@dataclass(frozen=True)
class TaskUsage:
    task: str
    calls: int
    errors: int
    """Baris berstatus `error` atau `empty` (respons kosong juga kegagalan bagi operator)."""
    prompt_tokens: int | None
    completion_tokens: int | None
    """Jumlah dari baris yang melaporkan token; None kalau tidak ada satu pun."""
    median_latency_ms: int | None
    prompt_version: str | None
    """Versi prompt pada baris terbaru task ini."""


class LlmCallRepo:
    """Sync."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        *,
        task: str,
        model: str,
        prompt_version: str | None,
        status: str,
        error_type: str | None,
        http_status: int | None,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        latency_ms: int,
    ) -> None:
        self.session.add(
            LlmCall(
                task=task,
                model=model,
                prompt_version=prompt_version,
                status=status,
                error_type=error_type,
                http_status=http_status,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
            )
        )

    def purge_older_than(self, cutoff: datetime.datetime) -> int:
        result = cast(
            "CursorResult[tuple[()]]",
            self.session.execute(delete(LlmCall).where(LlmCall.at < cutoff)),
        )
        return result.rowcount

    def latest_for_tasks(self, tasks: Sequence[str]) -> LlmCall | None:
        return self.session.execute(
            select(LlmCall)
            .where(LlmCall.task.in_(tasks))
            .order_by(LlmCall.at.desc(), LlmCall.id.desc())
            .limit(1)
        ).scalar_one_or_none()


class AsyncLlmCallRepo:
    """Async -- permukaan baca."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest_for_tasks(self, tasks: Sequence[str]) -> LlmCall | None:
        return (
            await self.session.execute(
                select(LlmCall)
                .where(LlmCall.task.in_(tasks))
                .order_by(LlmCall.at.desc(), LlmCall.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def latest_call_at(self) -> datetime.datetime | None:
        """Cap waktu baris terbaru dari task APA PUN."""
        return (await self.session.execute(select(func.max(LlmCall.at)))).scalar_one_or_none()

    async def latest_ok_at(self, tasks: Sequence[str]) -> datetime.datetime | None:
        return (
            await self.session.execute(
                select(func.max(LlmCall.at)).where(LlmCall.task.in_(tasks), LlmCall.status == "ok")
            )
        ).scalar_one_or_none()

    async def latest_failure(self, tasks: Sequence[str]) -> LlmCall | None:
        """Baris gagal (`error` atau `empty`) terbaru dari `tasks`."""
        return (
            await self.session.execute(
                select(LlmCall)
                .where(LlmCall.task.in_(tasks), LlmCall.status.in_(("error", "empty")))
                .order_by(LlmCall.at.desc(), LlmCall.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def usage_by_task(self, since: datetime.datetime) -> list[TaskUsage]:
        failed = func.count().filter(LlmCall.status.in_(("error", "empty")))
        median = func.percentile_cont(0.5).within_group(LlmCall.latency_ms)
        rows = (
            await self.session.execute(
                select(
                    LlmCall.task,
                    func.count(),
                    failed,
                    func.sum(LlmCall.prompt_tokens),
                    func.sum(LlmCall.completion_tokens),
                    median,
                )
                .where(LlmCall.at >= since)
                .group_by(LlmCall.task)
                .order_by(LlmCall.task)
            )
        ).all()
        # Versi prompt = baris terbaru per task (DISTINCT ON), satu query terpisah.
        versions = dict(
            (
                await self.session.execute(
                    select(LlmCall.task, LlmCall.prompt_version)
                    .where(LlmCall.at >= since)
                    .distinct(LlmCall.task)
                    .order_by(LlmCall.task, LlmCall.at.desc(), LlmCall.id.desc())
                )
            )
            .tuples()
            .all()
        )
        return [
            TaskUsage(
                task=task,
                calls=calls,
                errors=errors,
                prompt_tokens=int(pt) if pt is not None else None,
                completion_tokens=int(ct) if ct is not None else None,
                median_latency_ms=round(med) if med is not None else None,
                prompt_version=versions.get(task),
            )
            for task, calls, errors, pt, ct, med in rows
        ]
