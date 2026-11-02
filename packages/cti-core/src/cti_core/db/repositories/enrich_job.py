"""Repo `enrich_jobs` (P7g): tulis/klaim sync (Celery), baca/aksi analis async (API)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.models.enrich_job import EnrichJob
from cti_core.urlkit import url_hash as compute_url_hash

JSON_FAILURE_CAP = 3
"""Kegagalan JSON berurutan sebelum job jadi `failed`."""
BACKOFF_CAP_MIN = 60
"""Batas atas jeda gateway; jeda = `min(60, 2 ** attempts)` menit (attempts sesudah +1)."""
ERROR_MAX_CHARS = 300


@dataclass(frozen=True)
class JobCounts:
    pending_classify: int
    pending_ttp: int
    failed: int
    oldest_pending_at: datetime.datetime | None


def _trim(error: str) -> str:
    """Pemanggil sudah membersihkan rahasia (`_scrub_secrets`); di sini cuma dipotong."""
    return error[:ERROR_MAX_CHARS]


def _counts_query() -> Any:
    pending = EnrichJob.state == "pending"
    return select(
        func.count().filter(pending, EnrichJob.kind == "classify"),
        func.count().filter(pending, EnrichJob.kind == "ttp"),
        func.count().filter(EnrichJob.state == "failed"),
        func.min(EnrichJob.created_at).filter(pending),
    )


class EnrichJobRepo:
    """Sync -- dipakai pipeline, dispatcher, dan task `enrich.llm`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        kind: str,
        url: str,
        title: str,
        source: str,
        scraper_id: str | None,
        posted_on: datetime.date | None,
        input_text: str | None,
        context: dict[str, Any],
        article_id: int | None = None,
        state: str = "pending",
        last_error: str | None = None,
    ) -> EnrichJob | None:
        """`None` bila job `(kind, url)` sudah ada (ON CONFLICT DO NOTHING)."""
        stmt = (
            pg_insert(EnrichJob)
            .values(
                kind=kind,
                url=url,
                url_hash=compute_url_hash(url),
                title=title,
                source=source,
                scraper_id=scraper_id,
                posted_on=posted_on,
                article_id=article_id,
                input_text=input_text,
                context=context,
                state=state,
                last_error=None if last_error is None else _trim(last_error),
            )
            .on_conflict_do_nothing(index_elements=["kind", "url_hash"])
            .returning(EnrichJob.id)
        )
        job_id = self.session.execute(stmt).scalar_one_or_none()
        if job_id is None:
            return None
        job = self.session.get(EnrichJob, job_id)
        if job is not None:
            self.session.refresh(job)
        return job

    def has_classify(self, url_hash: str) -> bool:
        return (
            self.session.execute(
                select(EnrichJob.id).where(
                    EnrichJob.kind == "classify", EnrichJob.url_hash == url_hash
                )
            ).first()
            is not None
        )

    def get_for_update(self, job_id: int) -> EnrichJob | None:
        return self.session.execute(
            select(EnrichJob)
            .where(EnrichJob.id == job_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    def claim_due(
        self, now: datetime.datetime, *, limit: int, lease: datetime.timedelta
    ) -> list[EnrichJob]:
        """Job `pending` yang jatuh tempo, `classify` dulu lalu yang paling lama; `next_attempt_at`
        digeser `lease` supaya crash antara commit dan kirim tidak menimbulkan kirim ulang tanpa
        henti."""
        rows = list(
            self.session.execute(
                select(EnrichJob)
                .where(EnrichJob.state == "pending", EnrichJob.next_attempt_at <= now)
                .order_by(
                    case((EnrichJob.kind == "classify", 0), else_=1),
                    EnrichJob.created_at,
                    EnrichJob.id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            ).scalars()
        )
        for job in rows:
            job.next_attempt_at = now + lease
        self.session.flush()
        return rows

    def record_gateway_failure(self, job: EnrichJob, now: datetime.datetime, error: str) -> None:
        job.attempts += 1
        minutes = min(BACKOFF_CAP_MIN, 2**job.attempts)
        job.next_attempt_at = now + datetime.timedelta(minutes=minutes)
        job.last_error = _trim(error)
        self.session.flush()

    def record_json_failure(self, job: EnrichJob, now: datetime.datetime, error: str) -> bool:
        """True bila batas tercapai dan job menjadi `failed`; selain itu jatuh tempo lagi `now`."""
        job.json_failures += 1
        job.last_error = _trim(error)
        capped = job.json_failures >= JSON_FAILURE_CAP
        if capped:
            job.state = "failed"
        else:
            job.next_attempt_at = now
        self.session.flush()
        return capped

    def mark_failed(self, job: EnrichJob, error: str) -> None:
        job.state = "failed"
        job.last_error = _trim(error)
        self.session.flush()

    def delete(self, job: EnrichJob) -> None:
        self.session.delete(job)
        self.session.flush()

    def counts(self) -> JobCounts:
        pc, pt, f, oldest = self.session.execute(_counts_query()).one()
        return JobCounts(pc, pt, f, oldest)


class AsyncEnrichJobRepo:
    """Async -- permukaan API (daftar, coba ulang oleh analis)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        kind: str | None = None,
        state: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[EnrichJob], int]:
        conds: list[Any] = []
        if kind:
            conds.append(EnrichJob.kind == kind)
        if state:
            conds.append(EnrichJob.state == state)
        if search:
            conds.append(
                or_(EnrichJob.title.ilike(f"%{search}%"), EnrichJob.source.ilike(f"%{search}%"))
            )
        total = (
            await self.session.execute(select(func.count()).select_from(EnrichJob).where(*conds))
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    select(EnrichJob)
                    .where(*conds)
                    .order_by(EnrichJob.created_at.desc(), EnrichJob.id.desc())
                    .limit(page_size)
                    .offset((page - 1) * page_size)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def get(self, job_id: int) -> EnrichJob | None:
        return await self.session.get(EnrichJob, job_id)

    async def retry(self, job: EnrichJob, now: datetime.datetime) -> None:
        job.state = "pending"
        job.next_attempt_at = now
        job.json_failures = 0
        await self.session.flush()

    async def counts(self) -> JobCounts:
        pc, pt, f, oldest = (await self.session.execute(_counts_query())).one()
        return JobCounts(pc, pt, f, oldest)
