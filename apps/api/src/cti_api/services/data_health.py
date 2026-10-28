"""Halaman Data health (`GET /api/data-health`, ROADMAP #24 PR-B): satu payload untuk "apakah
pipeline sehat?" -- armada scraper, kegagalan enrichment, antrian `enrich`, kesegaran sumber, dan
cakupan enrichment IOC. Kesegaran CVE dan ATT&CK TIDAK disusun ulang di sini: halaman memanggil
`/api/cve/freshness` dan `/api/attack/status` yang sudah ada.

Cache 60 detik per proses (pola dashboard lain, tapi lebih pendek: ini halaman operasional);
didaftarkan di fixture autouse `_clear_in_process_caches`."""

from __future__ import annotations

import datetime
import time
from typing import Literal

from cti_core.config import get_settings
from cti_core.db.repositories.data_health import AsyncDataHealthRepo
from cti_core.db.repositories.llm_call import AsyncLlmCallRepo, TaskUsage
from cti_core.db.repositories.relevance import AsyncRelevanceModelRepo
from cti_core.db.repositories.story import AsyncStoryRepo, StoryStats
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.schemas.data_health import (
    DataHealthOut,
    EnrichmentHealthOut,
    IocEnrichmentTypeOut,
    LlmErrorOut,
    LlmHealthOut,
    LlmParkedOut,
    LlmTaskUsageOut,
    QueueHealthOut,
    RelevanceHealthOut,
    SourceFreshnessOut,
    StoryHealthOut,
)
from cti_api.services.scraper_health import build_scraper_health

_CACHE_TTL = 60.0
_cache: tuple[DataHealthOut, float] | None = None

# Nama list Celery untuk queue `enrich` (sama dengan `cti_scraper.sinks._ENRICH_QUEUE`).
_ENRICH_QUEUE = "enrich"

# Task yang menentukan status model: jalur enrichment artikel (kegagalan di sini memarkir artikel).
_STATUS_TASKS = ("classify", "ttp")


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


def _usage_out(rows: list[TaskUsage]) -> list[LlmTaskUsageOut]:
    return [
        LlmTaskUsageOut(
            task=u.task,
            calls=u.calls,
            errors=u.errors,
            prompt_tokens=u.prompt_tokens,
            completion_tokens=u.completion_tokens,
            median_latency_ms=u.median_latency_ms,
            prompt_version=u.prompt_version,
        )
        for u in rows
    ]


def _story_out(stats: StoryStats) -> StoryHealthOut:
    return StoryHealthOut(
        new_stories=stats.new_stories,
        followups=stats.followups,
        inherited=stats.inherited,
        llm_calls_avoided=stats.inherited * 2,
        by_embedding=stats.by_embedding,
    )


async def _llm_health(
    session: AsyncSession, repo: AsyncDataHealthRepo, now: datetime.datetime
) -> LlmHealthOut:
    calls = AsyncLlmCallRepo(session)
    latest = await calls.latest_for_tasks(_STATUS_TASKS)
    status: Literal["ok", "failing", "unknown"] = "unknown"
    if latest is not None:
        status = "ok" if latest.status == "ok" else "failing"
    error = await calls.latest_failure(_STATUS_TASKS)
    parked = await repo.parked_counts(now)
    stories = AsyncStoryRepo(session)
    return LlmHealthOut(
        status=status,
        last_call_at=_iso(await calls.latest_call_at()),
        last_ok_at=_iso(await calls.latest_ok_at(_STATUS_TASKS)),
        last_error=(
            LlmErrorOut(
                at=error.at.isoformat(),
                task=error.task,
                error_type=error.error_type
                or ("empty response" if error.status == "empty" else None),
                http_status=error.http_status,
            )
            if error is not None
            else None
        ),
        parked=LlmParkedOut(
            total=parked.total,
            auto_eligible=parked.auto_eligible,
            auto_replays_24h=parked.auto_replays_24h,
        ),
        usage_24h=_usage_out(await calls.usage_by_task(now - datetime.timedelta(hours=24))),
        usage_7d=_usage_out(await calls.usage_by_task(now - datetime.timedelta(days=7))),
        stories_24h=_story_out(await stories.stats_since(now - datetime.timedelta(hours=24))),
        stories_7d=_story_out(await stories.stats_since(now - datetime.timedelta(days=7))),
    )


def _ratio(part: int, whole: int) -> float | None:
    return part / whole if whole > 0 else None


async def _relevance_health(session: AsyncSession, now: datetime.datetime) -> RelevanceHealthOut:
    cfg = get_settings().relevance
    repo = AsyncRelevanceModelRepo(session)
    model = await repo.get_active()
    window = now - datetime.timedelta(days=cfg.gate_window_days)
    stats = await repo.gate_stats(since=window, revert_samples=cfg.revert_samples)
    metrics = model.metrics if model is not None else {}
    gate_state: Literal["shadow", "gate"] | None = None
    if model is not None:
        gate_state = "gate" if model.gate_state == "gate" else "shadow"
    return RelevanceHealthOut(
        mode=cfg.mode,
        gate_state=gate_state,
        gate_changed_at=_iso(model.gate_changed_at) if model is not None else None,
        model_trained_at=_iso(model.created_at) if model is not None else None,
        n_examples=model.n_examples if model is not None else None,
        holdout_agreement=metrics.get("agreement"),
        holdout_band_share=metrics.get("band_share"),
        band_titles_14d=stats.band_n,
        band_agreement_14d=_ratio(stats.band_agree, stats.band_n),
        middle_band_14d=await repo.middle_band_count(window),
        audit_samples=len(stats.audit_last),
        audit_agreement=_ratio(sum(stats.audit_last), len(stats.audit_last)),
        classify_avoided_24h=await repo.gated_count(now - datetime.timedelta(hours=24)),
        classify_avoided_7d=await repo.gated_count(now - datetime.timedelta(days=7)),
    )


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
        llm=await _llm_health(session, repo, now),
        relevance=await _relevance_health(session, now),
    )
