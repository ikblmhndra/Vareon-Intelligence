"""Dua jalur akses DB, satu model.

FastAPI (Fase 7) pakai sesi ASYNC (asyncpg) supaya request gak nge-block
event loop. Celery/CLI (Fase 3/6) pakai sesi SYNC (psycopg3) -- Celery task
itu proses worker biasa, gak ada event loop buat diblokir, dan sync jauh
lebih gampang di-debug/di-trace di sana.

Ini nyelesain konflik yang ada di sistem lama: scraper pakai pymongo sync,
web pakai motor async, dua driver beda buat DB yang sama. Di sini SATU
database, SATU set model SQLAlchemy, engine beda cuma di driver koneksi
(lihat DatabaseSettings.url vs .sync_url -- sama host/db, beda skema URI).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from cti_core.config import get_settings


@lru_cache(maxsize=1)
def get_async_engine() -> AsyncEngine:
    s = get_settings()
    return create_async_engine(
        s.database.url,
        pool_size=s.database.pool_size,
        max_overflow=s.database.max_overflow,
        pool_pre_ping=True,
        # pool_pre_ping: satu SELECT 1 murah sebelum checkout koneksi dari
        # pool -- ngilangin kelas bug "koneksi basi setelah DB restart /
        # idle timeout" yang di sistem lama gak ditangani sama sekali
        # (dbMongo.py malah bikin koneksi baru tiap panggilan, biaya jauh
        # lebih mahal buat masalah yang sama).
    )


@lru_cache(maxsize=1)
def get_sync_engine() -> Engine:
    s = get_settings()
    return create_engine(
        s.database.sync_url,
        pool_size=s.database.pool_size,
        max_overflow=s.database.max_overflow,
        pool_pre_ping=True,
        # Tanpa batas, host DB yang tidak menjawab (SYN hilang) menahan `connect()` sampai timeout
        # TCP OS (~2 menit). `runtime_secrets.overlay` memanggil sesi sync ini dari dalam event loop
        # API, jadi koneksi yang menggantung membekukan SELURUH proses API, bukan cuma satu request.
        connect_args={"connect_timeout": 5},
    )


@lru_cache(maxsize=1)
def _async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)


@lru_cache(maxsize=1)
def _sync_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(get_sync_engine(), expire_on_commit=False)


@asynccontextmanager
async def async_session() -> AsyncIterator[AsyncSession]:
    """Dipakai lewat FastAPI dependency:

        async def endpoint(session: AsyncSession = Depends(get_async_session)):
            ...

    Commit otomatis kalau blok `yield` sukses, rollback kalau exception,
    selalu close. Caller gak perlu manggil commit/rollback manual.
    """
    async with _async_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """Bentuk generator polos buat `Depends()` FastAPI (Fase 7) -- `Depends`
    butuh async generator function, bukan context manager langsung."""
    async with async_session() as session:
        yield session


@contextmanager
def sync_session() -> Iterator[Session]:
    """Dipakai task Celery / CLI:

    with sync_session() as session:
        ...
    """
    with _sync_sessionmaker()() as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


def discard_inherited_connections() -> None:
    """Panggil di PROSES ANAK sesaat setelah fork (Celery prefork:
    `worker_process_init`, lihat `cti_worker.celery_app`).

    Engine di-cache di proses INDUK (`lru_cache`) -- dan induk Celery beneran
    buka koneksi sebelum fork (`build_beat_schedule()` baca `ScraperConfig`
    pas import). Anak yang di-fork mewarisi socket yang SAMA; dua anak yang
    make koneksi itu barengan ngerusak protokol Postgres:
    `OperationalError: server closed the connection unexpectedly`, lalu
    `PendingRollbackError` di task berikutnya (kejadian nyata di e2e staging
    Fase 10, run scraper nyangkut `running`).

    `dispose(close=False)`: buang POOL warisan tanpa nutup koneksinya --
    nutup dari anak bakal ngirim Terminate ke server lewat socket yang masih
    dipakai induk. Engine tetap dipakai ulang, tinggal pool BARU per anak."""
    for factory in (get_sync_engine, get_async_engine):
        if factory.cache_info().currsize:  # belum pernah dibuat = gak ada yang diwarisi
            engine = factory()
            sync_engine = engine.sync_engine if isinstance(engine, AsyncEngine) else engine
            sync_engine.dispose(close=False)


def reset_engines() -> None:
    """Testing doang -- buang semua engine/sessionmaker singleton kalau
    Settings berubah di antar-test (mis. arah ke Postgres scratch beda)."""
    get_async_engine.cache_clear()
    get_sync_engine.cache_clear()
    _async_sessionmaker.cache_clear()
    _sync_sessionmaker.cache_clear()
