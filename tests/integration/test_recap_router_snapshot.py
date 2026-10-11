"""Snapshot test `routers/recap.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`). `recap_service._call_llm` di-mock, titik
sama kayak dipakai `_extract_json` (Fase 7.5) buat verifikasi kontrak."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from cti_api.services import recap as recap_service
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?generated_at$": (str,),
        # `/latest` dan `/generate` balikin "yesterday" relatif ke hari
        # jalan test (routers/recap.py), bukan tanggal tetap -- literal
        # ke-bake di snapshot bakal basi tiap hari kalender maju.
        r"(.*\.)?date$": (str,),
        # Panjang pesan user = panjang template prompt; tanpa ini snapshot ikut berubah setiap kali
        # teks prompt diedit, padahal yang dijaga di sini bentuk `token_usage`.
        r"(.*\.)?input_chars$": (int,),
    },
    regex=True,
    strict=False,
)

_FAKE_LLM_RESPONSE = (
    '{"headline": "Quiet day", "recap": {"summary": "No major incidents."}, '
    '"forecast": {"outlook": "stable"}}'
)
_FAKE_LLM_USAGE = {
    "prompt_tokens": 100,
    "completion_tokens": 20,
    "total_tokens": 120,
    "wall_ms": 7,
}


def _yesterday() -> str:
    return (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


async def test_recap_list_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/recap/list", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_recap_latest_none(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/recap/latest", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_recap_get_not_found(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/recap/2026-01-01", headers=auth_header())
    assert resp.status_code == 404
    assert resp.json() == snapshot


async def test_recap_generate(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    with patch.object(
        recap_service,
        "_call_llm",
        MagicMock(return_value=(_FAKE_LLM_RESPONSE, "test-model", _FAKE_LLM_USAGE)),
    ):
        resp = await api_client.post(
            "/api/recap/generate", headers=auth_header(), params={"date": _yesterday()}
        )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)
