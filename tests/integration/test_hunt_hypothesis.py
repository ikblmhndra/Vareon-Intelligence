# ruff: noqa: F811
"""Hipotesis hunting LLM (P7e Task 7) lewat HTTP ke Postgres nyata; `_call_llm` di-monkeypatch."""

from __future__ import annotations

import pytest
from cti_api.services import hunt_hypothesis
from cti_core.db.models.hunt import HuntHypothesis
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_hunt_packs_api import (  # noqa: F401  (fixture + helper)
    Header,
    Seeded,
    _own_sigma_rules,
    _token,
    seeded_story,
)

pytestmark = pytest.mark.asyncio


def _url(story: Seeded) -> str:
    return f"/api/hunt-packs/story/{story.id}/hypothesis"


async def test_generate_and_read(
    api_client: AsyncClient,
    auth_header: Header,
    seeded_story: Seeded,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str] = {}

    def fake(msg: str) -> str:
        seen["m"] = msg
        return "H1"

    monkeypatch.setattr(hunt_hypothesis, "_call_llm", fake)
    r = await api_client.post(_url(seeded_story), headers=auth_header(role="admin"))
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "H1" and r.json()["generated_by"] == "tester"
    assert "198.51.100.7" not in seen["m"] and "T1059 Cmd" in seen["m"]
    assert "T1190" not in seen["m"] and "network_traffic" in seen["m"]
    got = await api_client.get(_url(seeded_story), headers=auth_header(role="analyst"))
    assert got.json()["text"] == "H1"


async def test_get_404_when_none(
    api_client: AsyncClient, auth_header: Header, seeded_story: Seeded
) -> None:
    assert (await api_client.get(_url(seeded_story), headers=auth_header())).status_code == 404


async def test_regenerate_replaces(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Header,
    seeded_story: Seeded,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for text in ("first", "second"):
        monkeypatch.setattr(hunt_hypothesis, "_call_llm", lambda _m, t=text: t)
        r = await api_client.post(_url(seeded_story), headers=auth_header(role="admin"))
        assert r.json()["text"] == text
    count = await api_session.scalar(select(func.count()).select_from(HuntHypothesis))
    assert count == 1


async def test_llm_error_502_keeps_row(
    api_client: AsyncClient,
    auth_header: Header,
    seeded_story: Seeded,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = auth_header(role="admin")
    monkeypatch.setattr(hunt_hypothesis, "_call_llm", lambda _m: "keep")
    await api_client.post(_url(seeded_story), headers=h)

    def boom(_m: str) -> str:
        raise RuntimeError("llm down")

    monkeypatch.setattr(hunt_hypothesis, "_call_llm", boom)
    assert (await api_client.post(_url(seeded_story), headers=h)).status_code == 502
    assert (await api_client.get(_url(seeded_story), headers=h)).json()["text"] == "keep"


async def test_post_needs_manage_intel(
    api_client: AsyncClient, auth_header: Header, seeded_story: Seeded
) -> None:
    r = await api_client.post(_url(seeded_story), headers=auth_header(role="analyst"))
    assert r.status_code == 403


async def test_unknown_anchor_404(api_client: AsyncClient, auth_header: Header) -> None:
    r = await api_client.post(
        "/api/hunt-packs/story/987654321/hypothesis", headers=auth_header(role="admin")
    )
    assert r.status_code == 404


async def test_hypothesis_not_in_v2_pack(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Header,
    seeded_story: Seeded,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hunt_hypothesis, "_call_llm", lambda _m: "SECRETTEXT")
    await api_client.post(_url(seeded_story), headers=auth_header(role="admin"))
    h = await _token(api_session)
    await api_session.commit()
    r = await api_client.get(f"/api/v2/hunt-packs/story/{seeded_story.id}", headers=h)
    assert r.status_code == 200 and "hypothesis" not in r.text.lower()
    assert "SECRETTEXT" not in r.text
