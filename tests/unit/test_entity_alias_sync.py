"""Task `entity.alias_sync`: bagian tanpa DB (setelan, jadwal beat, fetch HTTP, task nonaktif).
Yang butuh Postgres ada di tests/integration/test_entity_alias_sync.py."""

from __future__ import annotations

import httpx
import pytest
import respx
from cti_core.config import EntitySettings, Settings
from cti_worker import beat


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch):
    from cti_core.config import get_settings

    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def entity_tasks():
    from cti_worker.tasks import entity

    return entity


def test_entity_setting_default_on() -> None:
    assert EntitySettings().alias_sync_enabled is True
    assert Settings(_env_file=None).entity.alias_sync_enabled is True


def test_entity_setting_rejects_unknown_key() -> None:
    with pytest.raises(ValueError):
        EntitySettings(typo=True)  # type: ignore[call-arg]


def test_alias_sync_scheduled_sunday_0500_maintenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})
    entry = beat.build_beat_schedule()["entity-alias-sync"]
    assert entry["task"] == "entity.alias_sync"
    assert entry["options"] == {"queue": "maintenance"}
    c = entry["schedule"]
    assert (str(c._orig_minute), str(c._orig_hour), str(c._orig_day_of_week)) == ("0", "5", "0")


def test_disabled_setting_skips(monkeypatch: pytest.MonkeyPatch, entity_tasks) -> None:
    monkeypatch.setenv("ENTITY__ALIAS_SYNC_ENABLED", "false")
    from cti_core.config import get_settings

    get_settings.cache_clear()
    try:
        assert entity_tasks.alias_sync() == {"skipped": "disabled"}
    finally:
        get_settings.cache_clear()


@respx.mock
def test_http_fetch_returns_json_with_30s_timeout(entity_tasks) -> None:
    route = respx.get(
        "https://raw.githubusercontent.com/MISP/misp-galaxy/main/clusters/malpedia.json"
    ).mock(return_value=httpx.Response(200, json={"values": []}))
    assert entity_tasks.http_fetch(entity_tasks.galaxy_url("malpedia")) == {"values": []}
    assert route.called


@respx.mock
def test_http_fetch_raises_on_http_error(entity_tasks) -> None:
    respx.get(entity_tasks.galaxy_url("ransomware")).mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        entity_tasks.http_fetch(entity_tasks.galaxy_url("ransomware"))
