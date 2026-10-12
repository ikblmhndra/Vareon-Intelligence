"""Task Celery `recap.generate_weekly` (`cti_worker.tasks.periodic`, #21 PR 2): hanya membungkus
`generate_weekly_recap` -- pekan terakhir yang sudah selesai, tanpa force. Jadwalnya dites di
`test_beat_schedule.py`, logikanya di `test_recap_weekly.py` dan `test_recap_service.py`."""

from __future__ import annotations

import contextlib
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


def test_the_task_generates_the_last_finished_week_without_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cti_worker.tasks import periodic

    calls: list[tuple[Any, Any, bool]] = []

    @contextlib.asynccontextmanager
    async def fake_session() -> AsyncIterator[str]:
        yield "SESSION"

    async def fake_generate(
        session: Any, week_start: Any = None, force: bool = False
    ) -> dict[str, object]:
        calls.append((session, week_start, force))
        return {"date": "2026-10-26", "cached": False}

    monkeypatch.setattr("cti_core.db.engine.async_session", fake_session)
    monkeypatch.setattr("cti_api.services.recap.generate_weekly_recap", fake_generate)

    result = periodic.generate_weekly_recap.run()

    # `week_start=None` = pekan terakhir yang SUDAH selesai di UTC (Senin 00:15 UTC: yang kemarin
    # berakhir); `force=False` = jalan ganda (`acks_late`) mengembalikan cache, bukan LLM lagi.
    assert calls == [("SESSION", None, False)]
    assert result == {"week_start": "2026-10-26", "cached": False}
