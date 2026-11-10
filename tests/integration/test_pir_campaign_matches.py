"""`GET /api/pir`: RFI tertaut dan kampanye cocok (opt-in `include_campaigns`)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from cti_core.db.repositories.rfi import AsyncRFIRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _camp(cid: str, score: int, pir_ids: list[int]) -> dict[str, Any]:
    return {
        "cluster_id": cid,
        "cluster_name": cid,
        "summary_title": f"Title {cid}" if score % 2 else "",
        "size": 4,
        "severity_score": score,
        "severity_label": "High",
        "last_seen": "2026-11-01",
        "matched_pirs": [{"id": i} for i in pir_ids],
    }


async def _pirs(session: AsyncSession) -> tuple[int, int, int]:
    await AsyncClientRepo(session).ensure_default()
    repo = AsyncPIRRepo(session)
    a = await repo.create({"title": "A", "priority": "P1"}, client_id="default")
    b = await repo.create({"title": "B", "priority": "P2"}, client_id="default")
    c = await repo.create({"title": "C", "priority": "P3"}, client_id="default")
    c.status = "paused"
    await session.commit()
    return a.id, b.id, c.id


def _patch(monkeypatch: pytest.MonkeyPatch, campaigns: list[dict[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def fake(session: AsyncSession, **kw: Any) -> list[dict[str, Any]]:
        seen.update(kw)
        return campaigns

    monkeypatch.setattr("cti_api.services.campaign.get_recent_campaigns", fake)
    return seen


async def test_campaigns_inverted_per_pir(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b, _ = await _pirs(api_session)
    camps = [_camp("low", 10, [a]), _camp("high", 90, [a, b])]
    camps += [_camp(f"x{i}", 20 + i, [b]) for i in range(6)]  # b: 7 kecocokan
    seen = _patch(monkeypatch, camps)

    resp = await api_client.get(
        "/api/pir?include_campaigns=true&campaign_days=14", headers=auth_header()
    )
    assert resp.status_code == 200, resp.text
    assert seen["days"] == 14
    assert seen["min_size"] == 3
    by_id = {p["id"]: p for p in resp.json()}
    assert [c["cluster_id"] for c in by_id[a]["matched_campaigns"]] == ["high", "low"]
    b_list = by_id[b]["matched_campaigns"]
    assert len(b_list) == 5
    assert b_list[0]["cluster_id"] == "high"
    scores = [c["cluster_id"] for c in b_list[1:]]
    assert scores == ["x5", "x4", "x3", "x2"]
    assert by_id[a]["matched_campaigns"][0]["severity_label"] == "High"


async def test_campaign_title_falls_back_to_cluster_id(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, _, _ = await _pirs(api_session)
    _patch(monkeypatch, [_camp("even", 10, [a]), _camp("odd", 11, [a])])
    resp = await api_client.get("/api/pir?include_campaigns=true", headers=auth_header())
    titles = {c["cluster_id"]: c["title"] for c in resp.json()[0]["matched_campaigns"]}
    assert titles == {"even": "even", "odd": "Title odd"}


async def test_paused_pir_gets_empty_list(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, _, c = await _pirs(api_session)
    _patch(monkeypatch, [_camp("k", 50, [a])])
    resp = await api_client.get("/api/pir?include_campaigns=true", headers=auth_header())
    by_id = {p["id"]: p for p in resp.json()}
    assert by_id[c]["matched_campaigns"] == []


async def test_campaigns_null_when_not_requested(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _pirs(api_session)

    async def boom(*a: Any, **k: Any) -> list[dict[str, Any]]:
        raise AssertionError("tidak boleh dipanggil")

    monkeypatch.setattr("cti_api.services.campaign.get_recent_campaigns", boom)
    resp = await api_client.get("/api/pir", headers=auth_header())
    assert resp.status_code == 200
    assert all(p["matched_campaigns"] is None for p in resp.json())


@pytest.mark.parametrize("days", [6, 91])
async def test_campaign_days_bounds(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]], days: int
) -> None:
    resp = await api_client.get(f"/api/pir?campaign_days={days}", headers=auth_header())
    assert resp.status_code == 422


async def test_put_returns_null_campaigns_and_linked_rfis(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    a, _, _ = await _pirs(api_session)
    await AsyncRFIRepo(api_session).create(
        {"requester": "r", "question": "x" * 200, "status": "in_progress", "linked_pir": a},
        client_id="default",
    )
    await api_session.commit()
    resp = await api_client.put(f"/api/pir/{a}", headers=auth_header(), json={"owner": "me"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matched_campaigns"] is None
    assert body["linked_rfi_open"] == 1
    assert len(body["linked_rfis"]) == 1
    assert len(body["linked_rfis"][0]["question"]) == 120

    listed = await api_client.get("/api/pir", headers=auth_header())
    assert listed.json()[0]["linked_rfi_open"] == 1
