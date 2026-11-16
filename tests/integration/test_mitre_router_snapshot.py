"""Snapshot test `routers/mitre.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`).

`GET /d3fend/{id}` manggil D3FEND API asli (`httpx.AsyncClient`) --
di-mock di titik import LANGSUNG router-nya (`from cti_api.services.
d3fend import get_d3fend_countermeasures`, jadi patch target-nya
`cti_api.routers.mitre.get_d3fend_countermeasures`, bukan modul
sumbernya)."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion

pytestmark = pytest.mark.asyncio


async def test_mitre_heatmap_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/mitre/heatmap", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_d3fend_countermeasures(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    fake_countermeasures = [{"technique_id": "D3-NTA", "name": "Network Traffic Analysis"}]
    with patch(
        "cti_api.routers.mitre.get_d3fend_countermeasures",
        AsyncMock(return_value=fake_countermeasures),
    ):
        resp = await api_client.get("/api/mitre/d3fend/T1566", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_navigator_layer_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/mitre/navigator-layer", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_navigator_export_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/mitre/navigator-export", headers=auth_header())
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == 'attachment; filename="cti_navigator_ta_90d.json"'
    assert resp.json() == snapshot


async def test_mitre_ttp_articles_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get(
        "/api/mitre/articles",
        headers=auth_header(),
        params={"ttp_id": "T1566", "row": "Apt41"},
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_navigator_export_heatmap_mode(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    params = {"view": "ta", "days": 90, "top_rows": 10, "top_ttps": 12}
    resp = await api_client.get("/api/mitre/navigator-export", params=params, headers=auth_header())
    assert resp.status_code == 200
    assert "_r10_c12" in resp.headers["content-disposition"]
    heat = await api_client.get("/api/mitre/heatmap", params=params, headers=auth_header())
    heat_ids = {t["id"] for t in heat.json()["ttps"] if t["id"].startswith("T")}
    assert {t["techniqueID"] for t in resp.json()["techniques"]} == heat_ids
