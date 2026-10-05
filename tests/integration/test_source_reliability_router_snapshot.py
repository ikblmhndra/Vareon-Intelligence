"""Snapshot test `routers/source_reliability.py` -- Fase 7.6 (lanjutan
pola pilot `test_cve_router_snapshot.py`)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_core.db.repositories.source_reliability import AsyncSourceReliabilityRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?added_date$": (str,),
        r"(.*\.)?last_updated$": (str,),
    },
    regex=True,
    strict=False,
)


async def _seed_entry(session: AsyncSession) -> None:
    await AsyncSourceReliabilityRepo(session).add_entry(
        source_name="gbhacker",
        analyst_name="analyst1",
        reliability_grade="B",
        credibility_code="2",
        notes="Consistently accurate",
    )


async def test_list_sr_entries(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_entry(api_session)
    resp = await api_client.get("/api/sr/entries", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_sr_stats(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_entry(api_session)
    resp = await api_client.get("/api/sr/stats", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_sr_labels(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/sr/labels", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_ungraded_sources_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/sr/ungraded-sources", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_add_sr_entry(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.post(
        "/api/sr/entries",
        headers=auth_header(),
        json={
            "source_name": "mandiant",
            "analyst_name": "analyst1",
            "reliability_grade": "A",
            "credibility_code": "1",
            "notes": "Highly reliable vendor",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_update_sr_entry(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_entry(api_session)
    entries, _ = await AsyncSourceReliabilityRepo(api_session).list_entries()
    resp = await api_client.put(
        f"/api/sr/entries/{entries[0].id}",
        headers=auth_header(),
        json={
            "analyst_name": "analyst1",
            "reliability_grade": "A",
            "credibility_code": "1",
            "notes": "Upgraded after review",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_delete_sr_entry(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_entry(api_session)
    entries, _ = await AsyncSourceReliabilityRepo(api_session).list_entries()
    resp = await api_client.delete(f"/api/sr/entries/{entries[0].id}", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot
