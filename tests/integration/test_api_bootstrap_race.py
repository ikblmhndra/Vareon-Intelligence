"""`cti_api.main.bootstrap_reference_rows` -- bootstrap client `default` + role
sistem yang dijalanin TIAP proses uvicorn pas start.

Regresi Fase 10.B: `WEB_CONCURRENCY=2` + DB KOSONG = dua proses sama-sama
lolos "cek dulu, baru insert" lalu tabrakan di `pk_clients`; yang kalah
crash di lifespan, uvicorn matiin container ("Child process failed to
start"). Ketauan cuma di deploy pertama (staging), gak di dev (satu proses,
DB sudah keisi).

Test ini MAKSA race-nya jadi deterministik: `AsyncClientRepo.get` ditahan
sebentar, jadi semua task pasti lolos cek sebelum ada yang sempat insert.
Tanpa advisory lock, test ini gagal (`IntegrityError`); dengan lock, task
kedua dst nunggu sampai yang pertama commit lalu cek-nya sudah lihat barisnya.

Commit BENERAN (tiap task pakai session/koneksi sendiri -- itu inti race-nya),
jadi baris hasilnya dibersihin manual di akhir supaya gak bocor ke test lain.
"""

from __future__ import annotations

import asyncio

import pytest
from cti_api.services.roles import SYSTEM_ROLES
from cti_core.db.engine import async_session
from cti_core.db.models.auth import Client, Role
from cti_core.db.models.source_reliability import SourceReliabilityEntry
from cti_core.db.repositories.auth import AsyncClientRepo
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def bootstrap_reference_rows(session: AsyncSession) -> None:
    """Import LAZY: `cti_api.main` bikin `app = create_app()` pas di-import, dan
    itu butuh `Settings` valid (env DATABASE__/AUTH__). Fixture `_migrated_schema`
    yang ngisi env-nya baru jalan SETELAH collection -- di mesin tanpa `.env`
    (CI) import di level modul = error collection, seluruh sesi pytest mati."""
    from cti_api.main import bootstrap_reference_rows as real

    await real(session)


@pytest.fixture
async def _clean_bootstrap_rows(_migrated_schema: None):
    async def wipe() -> None:
        async with async_session() as s:
            await s.execute(delete(Client).where(Client.client_id == "default"))
            await s.execute(delete(Role).where(Role.name.in_(list(SYSTEM_ROLES))))
            # baris grade bawaan yang dibuat bootstrap (0.8.6) jangan bocor ke test lain
            await s.execute(
                delete(SourceReliabilityEntry).where(SourceReliabilityEntry.origin == "default")
            )
            await s.commit()

    await wipe()
    yield
    await wipe()


async def test_concurrent_bootstrap_on_empty_db_does_not_collide(
    _clean_bootstrap_rows: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_get = AsyncClientRepo.get

    async def slow_get(self: AsyncClientRepo, client_id: str):  # type: ignore[no-untyped-def]
        result = await original_get(self, client_id)
        await asyncio.sleep(0.3)  # semua task lolos cek SEBELUM ada yang insert
        return result

    monkeypatch.setattr(AsyncClientRepo, "get", slow_get)

    async def one_process() -> None:
        async with async_session() as session:
            await bootstrap_reference_rows(session)

    await asyncio.gather(*(one_process() for _ in range(4)))  # gak boleh raise

    async with async_session() as s:
        clients = await s.scalar(
            select(func.count()).select_from(Client).where(Client.client_id == "default")
        )
        roles = await s.scalar(
            select(func.count()).select_from(Role).where(Role.name.in_(list(SYSTEM_ROLES)))
        )
        graded = (await s.scalars(select(SourceReliabilityEntry.source_name))).all()
    assert clients == 1
    assert roles == len(SYSTEM_ROLES)
    # grade bawaan per sumber scraper (0.8.6): ada, dan tidak dobel walau 4 proses bersamaan
    assert graded
    assert len({n.lower() for n in graded}) == len(graded)
