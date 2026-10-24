"""Task pemeliharaan LLM: replay otomatis artikel `[enrichment_failed]` dan retensi `llm_calls`.

`enrich.auto_replay` (tiap 10 menit) membaca status LLM terakhir dari `llm_calls` dan kedalaman
antrian `enrich`, lalu `cti_core.enrich_replay.plan_auto_replay` memutuskan berapa yang dikirim
(satu canary kalau model belum terbukti sehat). Urutan: tandai baris + COMMIT dulu, baru kirim, jadi
crash di antaranya tidak bisa membuat kirim-ulang tak berujung; gagal kirim setelah commit dicatat
saja (percobaan itu terhitung, backoff yang menjadwalkan ulang)."""

from __future__ import annotations

import datetime
from typing import Any

import structlog

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_MAINTENANCE

log = structlog.get_logger()

_LLM_TASKS = ("classify", "ttp")
_RETENTION = datetime.timedelta(days=90)


@app.task(name="enrich.auto_replay", queue=QUEUE_MAINTENANCE)
def auto_replay() -> dict[str, int]:
    from cti_core.celery_client import send_enrich_task
    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.article import RejectedArticleRepo
    from cti_core.db.repositories.llm_call import LlmCallRepo
    from cti_core.enrich_replay import BATCH, is_fresh, plan_auto_replay
    from cti_scraper.sinks import enrich_queue_depth

    now = datetime.datetime.now(datetime.UTC)
    with sync_session() as session:
        repo = RejectedArticleRepo(session)
        candidates = repo.auto_replay_candidates(now, BATCH)
        if not candidates:
            return {"sent": 0, "failed": 0}
        latest = LlmCallRepo(session).latest_for_tasks(_LLM_TASKS)
        chosen = plan_auto_replay(
            candidates,
            last_status=latest.status if latest else None,
            queue_depth=enrich_queue_depth(),
            max_depth=get_settings().scraper.enrich_queue_max_depth,
            now=now,
        )
        repo.mark_auto_replayed([c.id for c in chosen], now)
        session.commit()

    sent = failed = 0
    for c in chosen:
        try:
            send_enrich_task(
                title=c.title,
                url=c.url,
                posted_on=c.posted_on,
                source=c.source,
                scraper_id=c.scraper_id,
                replay=True,
                alert=is_fresh(c.posted_on, now),
            )
            sent += 1
        except Exception:
            failed += 1
            log.warning("auto_replay_send_failed", url=c.url, exc_info=True)
    log.info("auto_replayed", sent=sent, failed=failed, canary=len(chosen) == 1)
    return {"sent": sent, "failed": failed}


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
