"""Snapshot test `routers/exec_dashboard.py` -- Fase 7.6 (lanjutan pola
pilot `test_cve_router_snapshot.py`).

`POST /brief` manggil LLM asli (`exec_brief._call_llm`) -- di-mock,
titik yang sama kayak `test_ta_groups_router_snapshot.py`'s
`ta_profile._call_llm`."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from cti_api.services import exec_brief as exec_brief_service
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_NORMALIZE = path_type({r"(.*\.)?generated_at$": (str,)}, regex=True, strict=False)


async def test_dashboard_v1(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/exec/dashboard", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_dashboard_v2(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/exec/dashboard-v2", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_exec_brief(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    with patch.object(
        exec_brief_service, "_call_llm", MagicMock(return_value="# Executive Brief\n\nAll quiet.")
    ):
        resp = await api_client.post("/api/exec/brief", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)
