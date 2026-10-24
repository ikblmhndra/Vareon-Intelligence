"""Task `confidence.recompute_source`: hitung ulang `articles.confidence_score` untuk satu sumber
setelah grade-nya dibuat atau diubah (rilis 0.8.6, spec P2 5.2). Logikanya satu implementasi di
`cti_api.services.confidence` (lewat `_run_async`, pola sama task periodic lain).
Artikel dengan `overrides["confidence_score"]` dilewati."""

from __future__ import annotations

import structlog

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_MAINTENANCE
from cti_worker.tasks.periodic import _run_async

log = structlog.get_logger()


@app.task(name="confidence.recompute_source", queue=QUEUE_MAINTENANCE)
def recompute_source(source_name: str) -> dict[str, int]:
    from cti_api.services.confidence import recompute_all_confidence
    from cti_core.db.engine import async_session

    async def _run() -> dict[str, int]:
        async with async_session() as session:
            result = await recompute_all_confidence(session, source_name=source_name)
            await session.commit()
            return result

    result = _run_async(_run())
    log.info("confidence_recompute_source", source=source_name, **result)
    return result


@app.task(name="confidence.recompute_all", queue=QUEUE_MAINTENANCE)
def recompute_all() -> dict[str, int]:
    """Semua artikel (bootstrap grade bawaan). Idempoten; override analis dilewati."""
    from cti_api.services.confidence import recompute_all_confidence
    from cti_core.db.engine import async_session

    async def _run() -> dict[str, int]:
        async with async_session() as session:
            result = await recompute_all_confidence(session)
            await session.commit()
            return result

    result = _run_async(_run())
    log.info("confidence_recompute_all", **result)
    return result
