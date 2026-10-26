"""Task model relevansi lokal (P5): latih mingguan.

Import `cti_enrich` LAZY di dalam fungsi -- image `worker` tanpa extra `nlp` tetap harus bisa
start (lihat `tasks/enrich.py` dan `tasks/story.py`)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import structlog

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_ENRICH

log = structlog.get_logger()


def alert_ops(text: str, *, key: str, cooldown_s: int = 3600) -> None:
    """Satu alert Telegram per `key` per jendela cooldown (dedupe lewat Redis `SET NX EX`).
    BEST-EFFORT: tidak pernah melempar, supaya masalah alert tidak menutupi kerja aslinya
    (pola `_alert_enrichment_failure`)."""
    try:
        import redis
        from cti_alerts.telegram import send_alert
        from cti_core.config import get_settings

        client = redis.Redis.from_url(get_settings().redis.url)
        if not client.set(key, "1", nx=True, ex=cooldown_s):
            return
        send_alert("scraper_health", text)
    except Exception as alert_error:
        log.error("relevance_alert_failed", error=str(alert_error)[:200])


@app.task(name="relevance.train", queue=QUEUE_ENRICH)
def train() -> dict[str, Any]:
    import datetime

    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_enrich.relevance.embedder import get_embedder
    from cti_enrich.relevance.train import run_training

    # `sync_session` commit saat blok selesai: itu commit task ini (run_training tidak commit).
    with sync_session() as session:
        outcome = run_training(
            session, get_embedder(), get_settings().relevance, datetime.datetime.now(datetime.UTC)
        )
    log.info("relevance_trained", status=outcome.status, model_id=outcome.model_id)
    if outcome.status == "rejected":
        alert_ops(
            f"<b>Model relevansi baru DITOLAK</b>: {outcome.reason}. Model sebelumnya tetap aktif.",
            key="cti:relevance:train_rejected",
            cooldown_s=6 * 24 * 3600,
        )
    return asdict(outcome)
