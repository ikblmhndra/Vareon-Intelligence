"""Task `indicator.reconcile_validity`: isi/sinkronkan `indicators.valid_until` dari TTL settings
(P7a 3.3). Idempoten: dilewati bila sidik jari TTL tersimpan tidak berubah."""

from __future__ import annotations

import structlog

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_MAINTENANCE

log = structlog.get_logger()


@app.task(name="indicator.reconcile_validity", queue=QUEUE_MAINTENANCE)
def reconcile_validity() -> dict[str, int]:
    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.indicator import IndicatorRepo

    cfg = get_settings().indicator
    with sync_session() as session:
        result = IndicatorRepo(session).reconcile_validity(cfg)
    log.info("indicator_validity_reconciled", **result, **cfg.model_dump())
    return result
