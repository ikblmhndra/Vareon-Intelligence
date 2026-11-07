"""`cve.enrichment_sweep` (KEV + Exploit-DB + EPSS): satu session per langkah dan tidak ada
dua sweep sekaligus. Prod 2026-11-06: dua sweep (sisa antrean `maintenance`) jalan bersamaan,
yang pertama memegang satu transaksi > 75 menit, yang kedua dan promosi mirror menunggu lock."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> Any:
    from cti_core.config import get_settings

    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def periodic() -> Any:
    import cti_worker.celery_app  # noqa: F401  (mendaftarkan semua task; impor langsung = siklus)
    from cti_worker.tasks import periodic as mod

    return mod


class _FakeLock:
    def __init__(self, acquired: bool) -> None:
        self._acquired = acquired
        self.released = False

    def acquire(self) -> bool:
        return self._acquired

    def release(self) -> bool:
        self.released = True
        return True


def test_sweep_skips_when_another_sweep_holds_the_lock(periodic: Any) -> None:
    lock = _FakeLock(acquired=False)
    run = AsyncMock(return_value={})
    with (
        patch.object(periodic, "_sweep_lock", return_value=lock),
        patch.object(periodic, "_run_cve_enrichment", run),
    ):
        result = periodic.cve_enrichment_sweep.run()

    assert result == {"status": "skipped"}
    run.assert_not_awaited()
    assert lock.released is False


def test_sweep_releases_the_lock_even_when_it_fails(periodic: Any) -> None:
    lock = _FakeLock(acquired=True)
    with (
        patch.object(periodic, "_sweep_lock", return_value=lock),
        patch.object(periodic, "_run_cve_enrichment", AsyncMock(side_effect=RuntimeError("x"))),
        pytest.raises(RuntimeError),
    ):
        periodic.cve_enrichment_sweep.run()

    assert lock.released is True


def test_each_step_gets_its_own_session_and_a_failure_stays_in_its_step(periodic: Any) -> None:
    sessions: list[Any] = []

    @asynccontextmanager
    async def fake_session() -> AsyncIterator[Any]:
        session = MagicMock(name=f"session{len(sessions)}")
        sessions.append(session)
        yield session

    seen: dict[str, Any] = {}

    def step(name: str, result: Any) -> AsyncMock:
        async def run(session: Any) -> Any:
            seen[name] = session
            if isinstance(result, Exception):
                raise result
            return result

        return AsyncMock(side_effect=run)

    with (
        patch("cti_core.db.engine.async_session", fake_session),
        patch(
            "cti_api.services.cve_lookup.run_cisa_kev_lookup",
            step("cisa_kev", RuntimeError("kev down")),
        ),
        patch(
            "cti_api.services.cve_lookup.run_exploit_db_bulk_lookup",
            step("exploit_db", {"checked": 2}),
        ),
        patch("cti_api.services.cve_lookup.run_epss_lookup", step("epss", {"checked": 2})),
    ):
        results = periodic._run_async(periodic._run_cve_enrichment())

    assert results == {"exploit_db": {"checked": 2}, "epss": {"checked": 2}}
    assert len(sessions) == 3
    assert len({id(s) for s in seen.values()}) == 3
