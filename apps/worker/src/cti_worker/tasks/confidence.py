"""Task `confidence.recompute_source`: hitung ulang `articles.confidence_score` untuk satu sumber
setelah grade-nya dibuat atau diubah (rilis 0.8.6, spec P2 5.2). Logikanya satu implementasi di
`cti_api.services.confidence` (lewat `_run_async`, pola sama task periodic lain).
Artikel ber-override ikut dinilai ulang: `assess` yang menghormati override-nya (P6 4.5).
Semua task commit per batch (`commit_each_batch=True`): recompute penuh tidak memegang lock
baris sepanjang run. `confidence.refresh_stories` (P6 4.2) menilai ulang anggota story yang
baru tersentuh, karena kredibilitas anggota lama naik saat sumber independen baru bergabung."""

from __future__ import annotations

import datetime
from typing import Any

import structlog

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_MAINTENANCE
from cti_worker.tasks.periodic import _run_async

log = structlog.get_logger()

WATERMARK_KEY = "cti:confidence:refresh_stories:watermark"
"""Kunci Redis: ISO timestamp UTC awal run sukses terakhir `confidence.refresh_stories`."""
_DEFAULT_LOOKBACK = datetime.timedelta(hours=24)
# `stories.updated_at = now()` = waktu MULAI transaksi enrich (terbuka selama panggilan LLM, tanpa
# time_limit Celery), jadi query mundur 15 menit agar commit yang telat tidak terlewat.
_WATERMARK_OVERLAP = datetime.timedelta(minutes=15)


@app.task(name="confidence.recompute_source", queue=QUEUE_MAINTENANCE)
def recompute_source(source_name: str) -> dict[str, int]:
    from cti_api.services.confidence import recompute_all_confidence
    from cti_core.db.engine import async_session

    async def _run() -> dict[str, int]:
        async with async_session() as session:
            result = await recompute_all_confidence(
                session, source_name=source_name, commit_each_batch=True
            )
            await session.commit()
            return result

    result = _run_async(_run())
    log.info("confidence_recompute_source", source=source_name, **result)
    return result


@app.task(name="confidence.recompute_all", queue=QUEUE_MAINTENANCE)
def recompute_all() -> dict[str, int]:
    """Semua artikel (bootstrap grade bawaan, dan rekalkulasi harian). Idempoten; override
    analis dihormati di dalam `assess`, bukan dilewati."""
    from cti_api.services.confidence import recompute_all_confidence
    from cti_core.db.engine import async_session

    async def _run() -> dict[str, int]:
        async with async_session() as session:
            result = await recompute_all_confidence(session, commit_each_batch=True)
            await session.commit()
            return result

    result = _run_async(_run())
    log.info("confidence_recompute_all", **result)
    return result


async def refresh_stories(
    session: Any, redis_client: Any, now: datetime.datetime
) -> dict[str, int]:
    """Nilai ulang anggota story yang `updated_at`-nya sesudah watermark.

    `now` ditangkap pemanggil SEBELUM query dan jadi watermark baru hanya setelah recompute
    commit: story yang tersentuh selama run ikut terambil run berikutnya (at-least-once).
    Redis mati = `get` raise sebelum ada update, jadi run gagal keras dan tidak diam-diam
    memajukan watermark. Tanpa watermark: lihat 24 jam ke belakang."""
    from cti_api.services.confidence import recompute_all_confidence
    from cti_core.db.repositories.story import AsyncStoryRepo

    raw = redis_client.get(WATERMARK_KEY)
    if raw:
        text = raw.decode() if isinstance(raw, bytes) else raw
        since = datetime.datetime.fromisoformat(text)
    else:
        since = now - _DEFAULT_LOOKBACK

    story_ids = await AsyncStoryRepo(session).updated_since(since - _WATERMARK_OVERLAP)
    updated = 0
    if story_ids:
        result = await recompute_all_confidence(
            session, commit_each_batch=True, story_ids=story_ids
        )
        await session.commit()
        updated = result["updated"]
    redis_client.set(WATERMARK_KEY, now.isoformat())
    return {"stories": len(story_ids), "updated": updated}


@app.task(name="confidence.refresh_stories", queue=QUEUE_MAINTENANCE)
def refresh_stories_task() -> dict[str, int]:
    import redis
    from cti_core.config import get_settings
    from cti_core.db.engine import async_session

    async def _run() -> dict[str, int]:
        started = datetime.datetime.now(datetime.UTC)
        client = redis.Redis.from_url(get_settings().redis.url)
        try:
            async with async_session() as session:
                return await refresh_stories(session, client, started)
        finally:
            client.close()

    result = _run_async(_run())
    log.info("confidence_refresh_stories", **result)
    return result
