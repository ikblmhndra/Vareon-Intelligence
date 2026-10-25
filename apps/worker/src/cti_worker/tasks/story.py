"""Task pemeliharaan story: sapu story kosong.

Story kosong (lead ditolak, atau crash sebelum artikel pertama dipersist) tidak dihapus oleh
pipeline; sapuan harian ini satu-satunya yang membuangnya. Umur minimum = `story.max_age_days`,
jendela yang sama dengan kandidat resolver, jadi story yang masih bisa dipakai tidak tersapu."""

from __future__ import annotations

import datetime
from typing import Any

import structlog

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_MAINTENANCE

log = structlog.get_logger()


@app.task(name="story.purge_empty", queue=QUEUE_MAINTENANCE)
def purge_empty() -> dict[str, Any]:
    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.story import StoryRepo

    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        days=get_settings().story.max_age_days
    )
    with sync_session() as session:
        purged = StoryRepo(session).purge_empty(cutoff)
    log.info("empty_stories_purged", purged=purged)
    return {"purged": purged}
