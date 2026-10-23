"""Halaman Data health (`GET /api/data-health`, ROADMAP #24 PR-B): satu payload untuk "apakah
pipeline sehat?" -- armada scraper, kegagalan enrichment, antrian `enrich`, kesegaran sumber, dan
cakupan enrichment IOC. Kesegaran CVE dan ATT&CK TIDAK disusun ulang di sini: halaman memanggil
`/api/cve/freshness` dan `/api/attack/status` yang sudah ada.

Cache 60 detik per proses (pola dashboard lain, tapi lebih pendek: ini halaman operasional);
didaftarkan di fixture autouse `_clear_in_process_caches`."""

from __future__ import annotations

import datetime
import time

from cti_core.config import get_settings
from cti_core.db.repositories.data_health import AsyncDataHealthRepo
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.schemas.data_health import (
    DataHealthOut,
    EnrichmentHealthOut,
    IocEnrichmentTypeOut,
    QueueHealthOut,
    SourceFreshnessOut,
)
from cti_api.services.scraper_health import build_scraper_health

_CACHE_TTL = 60.0
_cache: tuple[DataHealthOut, float] | None = None

# Nama list Celery untuk queue `enrich` (sama dengan `cti_scraper.sinks._ENRICH_QUEUE`).
_ENRICH_QUEUE = "enrich"


def _iso(ts: datetime.datetime | None) -> str | None:
    return ts.isoformat() if ts is not None else None


async def get_data_health(session: AsyncSession, redis: Redis) -> DataHealthOut:
    global _cache
    mono = time.monotonic()
    if _cache is not None and (mono - _cache[1]) < _CACHE_TTL:
        return _cache[0]
    result = await _build(session, redis, datetime.datetime.now(datetime.UTC))
    _cache = (result, mono)
    return result


async def _enrich_depth(redis: Redis) -> int | None:
    """Redis gangguan = `None` (halaman tetap tampil), bukan 500."""
    try:
        return int(await redis.llen(_ENRICH_QUEUE))
    except Exception:
        return None


async def _build(session: AsyncSession, redis: Redis, now: datetime.datetime) -> DataHealthOut:
    repo = AsyncDataHealthRepo(session)
    # Sekuensial: satu `AsyncSession` tidak aman dipakai concurrent.
    scrapers = await build_scraper_health(session, redis, now)
    failures = await repo.enrichment_failures(now)
    processed = await repo.processed_since(now - datetime.timedelta(days=7))
    coverage = await repo.ioc_coverage_by_type()
    return DataHealthOut(
        generated_at=now.isoformat(),
        scrapers=scrapers,
        enrichment=EnrichmentHealthOut(
            failed_24h=failures.failed_24h,
            failed_7d=failures.failed_7d,
            processed_7d=processed,
            pending_replay=failures.pending_replay,
            last_failure_at=_iso(failures.last_failure_at),
        ),
        queues=QueueHealthOut(
            enrich_depth=await _enrich_depth(redis),
            enrich_max_depth=get_settings().scraper.enrich_queue_max_depth,
        ),
        sources=SourceFreshnessOut(
            articles_newest_at=_iso(await repo.newest_article_at()),
            tweets_newest_at=_iso(await repo.newest_tweet_at()),
            iocs_newest_at=_iso(await repo.newest_ioc_at()),
        ),
        ioc_enrichment=[
            IocEnrichmentTypeOut(type=c.type, total=c.total, enriched=c.enriched) for c in coverage
        ],
    )
