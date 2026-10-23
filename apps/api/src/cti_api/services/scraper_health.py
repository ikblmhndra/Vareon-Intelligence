"""Kesehatan armada scraper + heartbeat beat, dipakai `GET /api/scraper/health` DAN
`GET /api/data-health` (ROADMAP #24 PR-B). Dulu fungsi ini hidup di `routers/scraper.py`; dipindah
supaya halaman Data health tidak menyusun ulang aturan yang sama (status dihitung SATU tempat:
`cti_scraper.health.summarize_fleet_health`, fungsi murni yang juga dipakai digest worker)."""

from __future__ import annotations

import datetime

from cti_core import beat_heartbeat
from cti_core.config import get_settings
from cti_core.db.repositories.scraper import AsyncScraperConfigRepo, AsyncScraperRunRepo
from cti_scraper.health import summarize_fleet_health
from cti_scraper.registry import discover
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.schemas.scraper import (
    SchedulerStatusOut,
    ScraperHealthEntryOut,
    ScraperHealthSummary,
)


async def scheduler_status(redis: Redis, now: datetime.datetime) -> SchedulerStatusOut:
    """Heartbeat beat (QA BUG-D2/D8). Redis gak bisa dibaca = `unknown`, BUKAN
    500 -- list scraper tetap harus kebuka walau Redis lagi gangguan."""
    stale_after_s = get_settings().worker.beat_heartbeat_stale_s
    try:
        raw = await redis.get(beat_heartbeat.HEARTBEAT_KEY)
    except Exception:
        raw = None
    status = beat_heartbeat.classify(
        beat_heartbeat.parse(raw), now=now, stale_after_s=stale_after_s
    )
    return SchedulerStatusOut(
        state=status.state,
        last_tick_at=status.last_tick.isoformat() if status.last_tick else None,
        started_at=status.started_at.isoformat() if status.started_at else None,
        age_s=round(status.age_s, 1) if status.age_s is not None else None,
        stale_after_s=status.stale_after_s,
    )


async def build_scraper_health(
    session: AsyncSession, redis: Redis, now: datetime.datetime
) -> ScraperHealthSummary:
    registry = discover()
    configs = await AsyncScraperConfigRepo(session).get_all()
    run_repo = AsyncScraperRunRepo(session)
    recent_runs = await run_repo.list_recent_by_scraper_bulk(limit=3)
    last_success = await run_repo.last_success_by_scraper()
    entries = summarize_fleet_health(
        registry, configs, recent_runs, now=now, last_success=last_success
    )

    counts: dict[str, int] = {}
    problems: list[ScraperHealthEntryOut] = []
    for e in entries:
        counts[e.status] = counts.get(e.status, 0) + 1
        if e.status not in ("ok", "disabled"):
            problems.append(
                ScraperHealthEntryOut(
                    id=e.scraper_id,
                    source=e.source,
                    status=e.status,
                    last_status=e.last_status,
                    last_started_at=e.last_started_at.isoformat() if e.last_started_at else None,
                    reason=e.reason,
                    items_failed_last=e.items_failed_last,
                    consecutive_failing=e.consecutive_failing,
                    last_success_at=e.last_success_at.isoformat() if e.last_success_at else None,
                )
            )
    return ScraperHealthSummary(
        generated_at=now.isoformat(),
        counts=counts,
        scheduler=await scheduler_status(redis, now),
        problems=problems,
    )
