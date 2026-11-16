"""Nama queue di `/api/data-health` harus sama dengan konstanta worker."""

from __future__ import annotations

from cti_api.services.data_health import _QUEUES
from cti_scraper.queues import ALL_SCRAPE_QUEUES
from cti_worker import queues as w


def test_data_health_queue_names_match_worker() -> None:
    assert set(_QUEUES) == {
        *ALL_SCRAPE_QUEUES,
        w.QUEUE_ENRICH,
        w.QUEUE_NOTIFY,
        w.QUEUE_MAINTENANCE,
        w.QUEUE_CVE,
    }
    assert len(_QUEUES) == 7
