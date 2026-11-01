"""Snapshot test `routers/ta_groups.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`).

Sisa endpoint sesudah Threat Actor Room dipensiunkan (P7c-2): `/stats`, `/watchlist-names`,
`/watchlist/navigator-layer`."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_core.db.repositories.ta import AsyncTARepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion

pytestmark = pytest.mark.asyncio


async def _seed_group(session: AsyncSession) -> None:
    await AsyncTARepo(session).add_group("APT41")


async def test_ta_stats(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_group(api_session)
    resp = await api_client.get("/api/ta/stats", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_get_ta_watchlist_names_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/ta/watchlist-names", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_watchlist_navigator_layer_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/ta/watchlist/navigator-layer", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_watchlist_reads_ignore_a_foreign_client_header(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """Audit 2026-10-21: `X-Client-ID` milik client lain dulu diterima apa adanya. Sejak
    2026-10-24 header itu ditolak 403 (dulu diabaikan diam-diam)."""
    await AsyncTARepo(api_session).add_to_watchlist("Lazarus", "default")
    own = await api_client.get("/api/ta/watchlist-names", headers=auth_header())
    assert own.json() == {"names": ["Lazarus"]}  # kontrol: seed-nya memang terlihat

    outsider = {**auth_header(role="analyst", client_ids=["acme"]), "X-Client-ID": "default"}
    for path in ("/api/ta/watchlist-names", "/api/ta/watchlist/navigator-layer"):
        resp = await api_client.get(path, headers=outsider)
        assert resp.status_code == 403
        assert "Lazarus" not in resp.text
