"""Task pemeliharaan LLM: retensi `llm_calls`.

Replay otomatis artikel `[enrichment_failed]` yang dulu tinggal di sini pensiun di P7g: artikel
yang menunggu LLM tersimpan sebagai job `enrich_jobs` dan dikirim `enrich.llm_dispatch`."""

from __future__ import annotations

import datetime
from typing import Any

import structlog

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_MAINTENANCE

log = structlog.get_logger()

_RETENTION = datetime.timedelta(days=90)


@app.task(name="llm.purge_calls", queue=QUEUE_MAINTENANCE)
def purge_calls() -> dict[str, Any]:
    """Retensi `llm_calls`: 90 hari (cukup untuk tren /data-health; tabel tumbuh per panggilan)."""
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.llm_call import LlmCallRepo

    cutoff = datetime.datetime.now(datetime.UTC) - _RETENTION
    with sync_session() as session:
        deleted = LlmCallRepo(session).purge_older_than(cutoff)
    log.info("llm_calls_purged", deleted=deleted)
    return {"deleted": deleted}
