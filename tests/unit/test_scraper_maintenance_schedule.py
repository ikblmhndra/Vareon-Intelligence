"""Reaper run yatim dan purge riwayat run (ROADMAP #24) terdaftar di beat pada queue `maintenance`,
dan task-nya ada di Celery app. Jadwal dibangun sekali saat import: tanpa entri ini keduanya tidak
pernah jalan sampai ada yang sadar `scraper_runs` membengkak."""

from __future__ import annotations

import pytest
from cti_worker import beat


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from cti_core.config import get_settings

    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_reaper_and_purge_are_scheduled_on_the_maintenance_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})

    schedule = beat.build_beat_schedule()

    for name, task in {
        "scraper-reap-stale-runs": "scraper.reap_stale_runs",
        "scraper-purge-old-runs": "scraper.purge_old_runs",
    }.items():
        assert schedule[name]["task"] == task
        assert schedule[name]["options"] == {"queue": "maintenance"}


def test_the_maintenance_tasks_are_registered_in_the_celery_app() -> None:
    from cti_worker.celery_app import app
    from cti_worker.tasks import scrape  # noqa: F401  (mendaftarkan task)

    assert "scraper.reap_stale_runs" in app.tasks and "scraper.purge_old_runs" in app.tasks
