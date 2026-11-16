"""`POST /api/pir/preview`: hitungan pratinjau harus sama dengan `compute_coverage`."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_DAYS = 90


async def _seed(session: AsyncSession) -> datetime.date:
    await AsyncClientRepo(session).ensure_default()
    repo = AsyncArticleRepo(session)
    today = datetime.date.today()
    rows = [
        ("apt41-recent", "APT41 hits government network", 2, ["Apt41"]),
        ("apt41-mid", "APT41 second wave", 30, ["Apt41"]),
        ("apt41-old", "APT41 ancient", 200, ["Apt41"]),
        ("other", "Vendor update", 3, []),
    ]
    for slug, title, ago, actors in rows:
        a = await repo.upsert(
            url=f"https://example.com/{slug}",
            title=title,
            source="gbhacker",
            posted_on=today - datetime.timedelta(days=ago),
            news_type="apac",
        )
        if actors:
            await repo.set_enrichment(a, threat_actors=actors)
    await session.commit()
    return today - datetime.timedelta(days=_DAYS)


async def _coverage(session: AsyncSession, criteria: dict, since: datetime.date) -> int:
    pir = await AsyncPIRRepo(session).create(
        {"title": "cov", "criteria": criteria, "start_date": since}, client_id="default"
    )
    total, _, _ = await AsyncPIRRepo(session).compute_coverage(
        AsyncArticleRepo(session), pir.criteria, pir.start_date, pir.end_date
    )
    return total


async def test_preview_equals_coverage_total(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    since = await _seed(api_session)
    criteria = {"threat_actors": ["Apt41"]}
    resp = await api_client.post(
        "/api/pir/preview", headers=auth_header(), json={"criteria": criteria, "days": _DAYS}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 2
    assert body["count"] == await _coverage(api_session, criteria, since)
    assert body["days"] == _DAYS
    assert body["since"] == since.isoformat()
    assert body["has_criteria"] is True


async def test_empty_criteria_has_criteria_false(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _seed(api_session)
    resp = await api_client.post(
        "/api/pir/preview", headers=auth_header(), json={"criteria": {}, "days": _DAYS}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_criteria"] is False
    assert resp.json()["count"] == 3  # semua artikel dalam jendela, tanpa filter


async def test_preview_requires_manage_pir(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    resp = await api_client.post(
        "/api/pir/preview",
        # analyst sendiri punya `manage_pir`; role tanpa permission itu yang harus ditolak.
        headers=auth_header(username="bob", role="nobody"),
        json={"criteria": {}},
    )
    assert resp.status_code == 403, resp.text


async def test_preview_422_body(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    resp = await api_client.post(
        "/api/pir/preview", headers=auth_header(), json={"criteria": {}, "days": 0}
    )
    assert resp.status_code == 422


async def test_preview_matches_coverage_with_blank_keyword(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    """Chip kosong/duplikat (`keywords: [" "]`) tidak boleh membuat pratinjau menyimpang dari
    cakupan PIR yang tersimpan: keduanya memakai `criteria_filters` yang sama."""
    since = await _seed(api_session)
    for criteria in (
        {"keywords": [" "]},
        {"keywords": ["APT41", "apt41", " "]},
        {"threat_actors": ["Apt41"], "keywords": [""]},
    ):
        resp = await api_client.post(
            "/api/pir/preview", headers=auth_header(), json={"criteria": criteria, "days": _DAYS}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == await _coverage(api_session, criteria, since), criteria
