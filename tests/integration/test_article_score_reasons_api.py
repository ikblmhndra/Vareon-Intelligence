"""Alasan skor PIR / aset sendiri (P7f) di `ArticleOut.score_reasons`, disaring per client."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_REASONS = {
    "credibility": [],
    "priority": [{"code": "pir_match", "points": 20}],
    "pir": [
        {"id": 1, "title": "Ransomware default", "priority": "P1", "client_id": "default"},
        {"id": 2, "title": "Rahasia acme", "priority": "P2", "client_id": "acme"},
    ],
    "own_asset": [
        {"name": "FortiOS", "client_id": "default"},
        {"name": "Exchange", "client_id": "acme"},
    ],
}


async def _seed(api_session: AsyncSession, reasons: dict[str, object]) -> int:
    await AsyncClientRepo(api_session).ensure_default()
    a = await AsyncArticleRepo(api_session).upsert(
        url="https://r.example/1",
        title="Reasons",
        source="s",
        posted_on=datetime.date.today(),
    )
    a.score_reasons = reasons
    await api_session.commit()
    return a.id


async def test_detail_shows_only_own_client_reasons(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    aid = await _seed(api_session, _REASONS)
    h = {**auth_header(client_ids=["default", "acme"]), "X-Client-ID": "default"}
    sr = (await api_client.get(f"/api/articles/{aid}", headers=h)).json()["score_reasons"]
    assert sr["pir"] == [{"id": 1, "title": "Ransomware default", "priority": "P1"}]
    assert sr["own_asset"] == ["FortiOS"]
    assert sr["priority"] == [{"code": "pir_match", "points": 20}]


async def test_list_filters_reasons_per_client(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed(api_session, _REASONS)
    h = {**auth_header(client_ids=["default", "acme"]), "X-Client-ID": "acme"}
    sr = (await api_client.get("/api/articles", headers=h)).json()["articles"][0]["score_reasons"]
    assert [p["id"] for p in sr["pir"]] == [2]
    assert sr["own_asset"] == ["Exchange"]


async def test_serialize_without_client_hides_reasons(api_session: AsyncSession) -> None:
    from cti_api.routers.articles import _serialize

    await AsyncClientRepo(api_session).ensure_default()
    repo = AsyncArticleRepo(api_session)
    a = await repo.upsert(url="https://r.example/2", title="T", source="s")
    a.score_reasons = _REASONS
    await api_session.commit()
    a = await repo.get_by_id(a.id)  # type: ignore[assignment]  # relasi mention ikut dimuat
    out = _serialize(a, repo.to_dict(a), client_id=None)
    assert out.score_reasons.pir == [] and out.score_reasons.own_asset == []
    assert out.score_reasons.priority[0].code == "pir_match"


async def test_malformed_reason_entries_skipped(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    aid = await _seed(
        api_session, {"pir": ["x", {"id": 1}], "own_asset": [3, {"client_id": "default"}]}
    )
    resp = await api_client.get(f"/api/articles/{aid}", headers=auth_header())
    assert resp.status_code == 200
    sr = resp.json()["score_reasons"]
    assert sr["pir"] == [] and sr["own_asset"] == []
