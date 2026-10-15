"""Task `ioc.enrich_pending` (`cti_worker.tasks.periodic`): terdaftar di antrean `maintenance` dan
no-op tanpa kunci provider (tidak menyentuh DB maupun jaringan)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from cti_core.config import get_settings


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test")
    monkeypatch.delenv("ABUSEIPDB__API_KEY", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_the_task_is_registered_on_the_maintenance_queue() -> None:
    from cti_worker.queues import QUEUE_MAINTENANCE
    from cti_worker.tasks import periodic

    assert periodic.ioc_enrich_pending.name == "ioc.enrich_pending"
    assert periodic.ioc_enrich_pending.queue == QUEUE_MAINTENANCE


def test_without_provider_keys_the_run_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from cti_worker.tasks import periodic

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("tidak boleh menyentuh DB tanpa kunci provider")

    monkeypatch.setattr("cti_core.db.engine.async_session", boom)

    assert asyncio.run(periodic._run_ioc_enrich_pending()) == {}
