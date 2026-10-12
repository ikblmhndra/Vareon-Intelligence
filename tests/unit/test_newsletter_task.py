"""Task Celery `newsletter.prepare_monthly` (`cti_worker.tasks.periodic`, #22 PR 8): hanya
membungkus `prepare_monthly` dengan sesi `async_session()` (yang commit saat sukses) dan jam
sekarang (UTC, aware). Jadwalnya dites di `test_beat_schedule.py`, logikanya di
`test_newsletter_schedule.py`."""

from __future__ import annotations

import contextlib
import datetime
from collections.abc import AsyncIterator
from typing import Any

import pytest


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


def test_the_task_hands_the_session_and_the_current_utc_time_to_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cti_worker.tasks import periodic

    calls: list[tuple[Any, datetime.datetime]] = []

    @contextlib.asynccontextmanager
    async def fake_session() -> AsyncIterator[str]:
        yield "SESSION"

    async def fake_prepare(session: Any, now_utc: datetime.datetime) -> dict[str, object]:
        calls.append((session, now_utc))
        return {"prepared": False, "period_start": "2026-10-01"}

    monkeypatch.setattr("cti_core.db.engine.async_session", fake_session)
    monkeypatch.setattr("cti_api.services.newsletter_schedule.prepare_monthly", fake_prepare)

    before = datetime.datetime.now(datetime.UTC)
    result = periodic.prepare_newsletter_monthly.run()

    assert result == {"prepared": False, "period_start": "2026-10-01"}
    [(session, now)] = calls
    assert session == "SESSION"
    assert now.tzinfo is not None and now.utcoffset() == datetime.timedelta(0)
    assert before <= now <= datetime.datetime.now(datetime.UTC)


def test_a_failure_propagates_so_the_session_rolls_back_and_the_next_weekday_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cti_worker.tasks import periodic

    state = {"exit": None}

    @contextlib.asynccontextmanager
    async def fake_session() -> AsyncIterator[str]:
        try:
            yield "SESSION"
        except BaseException as exc:  # seperti `async_session`: rollback lalu lempar ulang
            state["exit"] = type(exc).__name__
            raise

    async def broken(session: Any, now_utc: datetime.datetime) -> dict[str, object]:
        raise RuntimeError("gateway down")

    monkeypatch.setattr("cti_core.db.engine.async_session", fake_session)
    monkeypatch.setattr("cti_api.services.newsletter_schedule.prepare_monthly", broken)

    with pytest.raises(RuntimeError, match="gateway down"):
        periodic.prepare_newsletter_monthly.run()

    assert state["exit"] == "RuntimeError"
