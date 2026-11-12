"""`brief_today` dan `DEFAULT_FILTERS` (tanggal brief = tanggal Jakarta, dipakai API dan worker)."""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import pytest
from cti_api.services.exec_brief import DEFAULT_FILTERS, brief_today
from cti_core.config import get_settings


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _utc(h: int, m: int) -> datetime.datetime:
    return datetime.datetime(2026, 11, 10, h, m, tzinfo=datetime.UTC)


def test_brief_today_before_boundary() -> None:
    assert brief_today(_utc(16, 59)) == datetime.date(2026, 11, 10)


def test_brief_today_at_boundary() -> None:
    assert brief_today(_utc(17, 0)) == datetime.date(2026, 11, 11)


def test_brief_today_offset_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER__REPORT_UTC_OFFSET_HOURS", "0")
    get_settings.cache_clear()
    assert brief_today(_utc(17, 0)) == datetime.date(2026, 11, 10)


def test_default_filters_json() -> None:
    assert DEFAULT_FILTERS.as_json() == {"days": 90, "incident_only": True, "confirmed_only": False}
