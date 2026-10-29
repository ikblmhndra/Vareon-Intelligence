"""Integration test `cti_api.services.ioc_decay` -- Fase 7.8 (Celery beat
"IOC decay", salah satu dari 5 loop). Postgres REAL (testcontainers).

Port `decay_sweep()` lama -- IOC yang `confidence_decayed_at` NULL atau
lebih tua dari 24 jam kena refresh, yang masih fresh (< 24 jam) DIBIARIN
(gak nyentuh `apply_confidence_and_actionability` sama sekali, jadi
`confidence_decayed_at`-nya tetep sama persis kayak sebelum sweep)."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services.ioc_decay import decay_sweep
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_decay_sweep_updates_never_decayed_ioc(async_db_session: AsyncSession) -> None:
    ioc = await AsyncIndicatorRepo(async_db_session).upsert(
        type="ip", value="203.0.113.5", source_url="https://x.example", source_name="s"
    )
    assert ioc.confidence_decayed_at is None

    result = await decay_sweep(async_db_session)

    assert result == {"scanned": 1, "updated": 1}
    await async_db_session.refresh(ioc)
    assert ioc.confidence_decayed_at is not None


async def test_decay_sweep_skips_recently_decayed_ioc(async_db_session: AsyncSession) -> None:
    ioc = await AsyncIndicatorRepo(async_db_session).upsert(
        type="domain", value="fresh.example", source_url="https://x.example", source_name="s"
    )
    recent = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    ioc.confidence_decayed_at = recent
    await async_db_session.flush()

    result = await decay_sweep(async_db_session)

    assert result == {"scanned": 0, "updated": 0}
    await async_db_session.refresh(ioc)
    assert ioc.confidence_decayed_at == recent


async def test_decay_sweep_refreshes_stale_ioc(async_db_session: AsyncSession) -> None:
    ioc = await AsyncIndicatorRepo(async_db_session).upsert(
        type="domain", value="stale.example", source_url="https://x.example", source_name="s"
    )
    stale = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=48)
    ioc.confidence_decayed_at = stale
    await async_db_session.flush()

    result = await decay_sweep(async_db_session)

    assert result == {"scanned": 1, "updated": 1}
    await async_db_session.refresh(ioc)
    assert ioc.confidence_decayed_at > stale
