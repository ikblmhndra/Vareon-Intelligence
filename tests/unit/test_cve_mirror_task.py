"""Lapisan task mirror CVE (`cti_worker.tasks.cve_mirror`): mati secara default (deploy skema
tidak mengubah perilaku), terdaftar di Celery + beat, fetcher httpx memetakan semua kegagalan ke
`FetchError`, dan flag/env konsisten. Logika sync-nya dites di `test_cve_mirror_sync.py`."""

from __future__ import annotations

import httpx
import pytest
from cti_core.config import CveMirrorSettings
from cti_core.cve_mirror_sync import DELTA_LOG_URL, DELTA_URL, FetchError
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


def test_mirror_is_disabled_by_default() -> None:
    assert CveMirrorSettings().enabled is False


def test_disabled_tasks_return_without_touching_db_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cti_worker.tasks import cve_mirror

    class Cfg:
        cve_mirror = CveMirrorSettings(enabled=False)

    monkeypatch.setattr(cve_mirror, "get_settings", lambda: Cfg())

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("tidak boleh menyentuh DB/jaringan saat mati")

    monkeypatch.setattr("cti_core.db.engine.sync_session", boom)
    monkeypatch.setattr(httpx, "Client", boom)
    assert cve_mirror.cve_mirror_sync.run() == {"status": "disabled"}
    assert cve_mirror.cve_mirror_purge.run() == {"status": "disabled"}


def test_tasks_are_registered_and_scheduled(monkeypatch: pytest.MonkeyPatch) -> None:
    from cti_worker.celery_app import app

    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})
    schedule = beat.build_beat_schedule()
    for name, task in (
        ("cve-mirror-sync", "cve.mirror_sync"),
        ("cve-mirror-purge", "cve.mirror_purge"),
    ):
        assert schedule[name]["task"] == task and task in app.tasks
        assert schedule[name]["options"] == {"queue": "maintenance"}
    assert sorted(schedule["cve-mirror-sync"]["schedule"].minute) == list(range(0, 60, 5))


def test_fetcher_returns_body_and_maps_every_failure_to_fetch_error() -> None:
    from cti_worker.tasks.cve_mirror import make_fetcher

    seen: dict[str, float] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[str(request.url)] = request.extensions["timeout"]["read"]
        if request.url.path.endswith("missing.json"):
            return httpx.Response(404)
        if request.url.path.endswith("down.json"):
            raise httpx.ConnectError("boom")
        return httpx.Response(200, content=b"{}")

    fetch = make_fetcher(httpx.Client(transport=httpx.MockTransport(handler)), 30.0)
    assert fetch(DELTA_URL) == b"{}"
    with pytest.raises(FetchError, match="HTTP 404"):
        fetch("https://raw.githubusercontent.com/x/missing.json")
    with pytest.raises(FetchError, match="ConnectError"):
        fetch("https://raw.githubusercontent.com/x/down.json")
    fetch(DELTA_LOG_URL)
    # deltaLog.json (24 MB): timeout lebih longgar
    assert seen[DELTA_URL] == 30.0 and seen[DELTA_LOG_URL] == 90.0
