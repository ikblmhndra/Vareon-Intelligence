"""Lifespan API: SATU antrean recompute-all setelah grade bawaan dibuat (0.8.6)."""

from __future__ import annotations

import pytest
from cti_api.services.roles import SYSTEM_ROLES
from cti_core.db.engine import async_session
from cti_core.db.models.auth import Client, Role
from cti_core.db.models.source_reliability import SourceReliabilityEntry
from sqlalchemy import delete

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _keep_logging_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """`lifespan` memanggil `configure_logging()` yang mengubah konfigurasi structlog global
    (`cache_logger_on_first_use=True`) dan tidak pernah dibatalkan. Logger modul yang dipakai
    sesudahnya ikut terkunci ke konfigurasi itu, sehingga `structlog.testing.capture_logs()` di
    test lain (mis. `tests/unit/test_newsletter_summary.py`) tidak menangkap apa pun saat seluruh
    `tests/` dijalankan sekaligus seperti di CI. Konfigurasi logging bukan yang diuji di sini."""
    monkeypatch.setattr("cti_api.main.configure_logging", lambda **_: None)


@pytest.fixture
async def _no_default_rows(_migrated_schema: None):
    async def wipe() -> None:
        async with async_session() as s:
            # lifespan juga membuat client default + role sistem; jangan bocor ke test lain
            await s.execute(delete(Client).where(Client.client_id == "default"))
            await s.execute(delete(Role).where(Role.name.in_(list(SYSTEM_ROLES))))
            await s.execute(
                delete(SourceReliabilityEntry).where(SourceReliabilityEntry.origin == "default")
            )
            await s.commit()

    await wipe()
    yield
    await wipe()


async def _run_lifespan() -> None:
    from cti_api.main import create_app, lifespan

    async with lifespan(create_app()):
        pass


async def test_startup_enqueues_exactly_one_recompute_all(
    _no_default_rows: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr("cti_api.main.send_recompute_all", lambda: calls.append(1))

    await _run_lifespan()
    assert calls == [1]  # banyak sumber baru, tetap satu pesan

    await _run_lifespan()
    assert calls == [1]  # start kedua: tidak ada baris baru, tidak ada antrean


async def test_startup_survives_failed_enqueue(
    _no_default_rows: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise ConnectionError("broker down")

    monkeypatch.setattr("cti_api.main.send_recompute_all", boom)
    await _run_lifespan()  # tidak boleh raise
