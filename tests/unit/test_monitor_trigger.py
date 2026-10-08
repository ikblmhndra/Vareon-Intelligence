"""Pemicu promosi dari API (`cti_api.services.monitor`) dan tugas `cve.promote_entry`: mati bila
mirror/promosi belum dinyalakan, kegagalan broker tidak menggagalkan request."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from cti_api.services import monitor


def settings(enabled: bool, promote: str) -> Any:
    return SimpleNamespace(cve_mirror=SimpleNamespace(enabled=enabled, promote=promote))


class FakeCelery:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, dict[str, Any], str]] = []
        self.fail = fail

    def send_task(self, name: str, kwargs: dict[str, Any], queue: str) -> None:
        if self.fail:
            raise ConnectionError("broker mati")
        self.sent.append((name, kwargs, queue))


@pytest.mark.parametrize(
    ("enabled", "promote"), [(False, "shadow"), (False, "live"), (True, "off"), (False, "off")]
)
def test_nothing_is_sent_unless_mirror_and_promotion_are_both_on(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, promote: str
) -> None:
    celery = FakeCelery()
    monkeypatch.setattr(monitor, "get_settings", lambda: settings(enabled, promote))
    monkeypatch.setattr(monitor, "get_celery_client", lambda: celery)
    assert monitor.enqueue_promote_entry(7) is False and celery.sent == []


@pytest.mark.parametrize("promote", ["shadow", "live"])
def test_task_is_sent_by_name_to_the_maintenance_queue(
    monkeypatch: pytest.MonkeyPatch, promote: str
) -> None:
    celery = FakeCelery()
    monkeypatch.setattr(monitor, "get_settings", lambda: settings(True, promote))
    monkeypatch.setattr(monitor, "get_celery_client", lambda: celery)
    assert monitor.enqueue_promote_entry(7) is True
    assert celery.sent == [("cve.promote_entry", {"entry_id": 7}, "maintenance")]


def test_a_dead_broker_never_fails_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitor, "get_settings", lambda: settings(True, "live"))
    monkeypatch.setattr(monitor, "get_celery_client", lambda: FakeCelery(fail=True))
    assert monitor.enqueue_promote_entry(7) is False


def test_promote_entry_task_is_registered_and_off_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cti_core.config import get_settings

    for k, v in {
        "DATABASE__URL": "postgresql+asyncpg://x:x@127.0.0.1:1/x",
        "DATABASE__SYNC_URL": "postgresql+psycopg://x:x@127.0.0.1:1/x",
        "AUTH__JWT_SECRET": "t",
        "AUTH__SESSION_SECRET_KEY": "t",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    try:
        from cti_worker.celery_app import app
        from cti_worker.tasks import cve_mirror

        assert "cve.promote_entry" in app.tasks
        assert cve_mirror.cve_promote_entry.run(5) == {"status": "disabled"}
    finally:
        get_settings.cache_clear()
