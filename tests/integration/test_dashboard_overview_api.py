"""Endpoint `/api/dashboard/{map,attention,trending,ransomware,cve-exposure}` lewat HTTP
(auth JWT asli, scope client lewat `X-Client-ID`) -- Postgres REAL."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.ransomware import RansomwareVictim
from cti_core.db.models.ta import TAWatchlistEntry
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_TODAY = datetime.date.today()


async def _seed_actor_articles(session: AsyncSession, n: int, actor: str = "Qilin") -> None:
    repo = AsyncArticleRepo(session)
    for i in range(n):
        a = await repo.upsert(
            url=f"https://example.com/{actor}-{i}",
            title=f"{actor} {i}",
            source="S",
            posted_on=_TODAY,
            confirmed_incident=True,
        )
        await repo.set_enrichment(a, threat_actors=[actor])


async def test_dashboard_endpoints_return_200_and_shape(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    h = auth_header()
    expected = {
        "map": {"points", "client_countries", "generated_at"},
        "attention": {
            "kev_in_stack",
            "kev_without_ticket",
            "ransomware_in_client_scope",
            "watchlist_hits",
            "pir_hits",
            "brief",
            "generated_at",
        },
        "trending": {"items", "window_days", "window_label", "generated_at"},
        "ransomware": {"weekly", "top_groups", "total", "apac", "undated", "generated_at"},
        "cve-exposure": {
            "items",
            "open_critical",
            "open_kev",
            "closed_in_period",
            "mean_days_to_close",
            "generated_at",
        },
    }
    for name, keys in expected.items():
        r = await api_client.get(f"/api/dashboard/{name}", params={"days": 7}, headers=h)
        assert r.status_code == 200, (name, r.text)
        assert keys <= set(r.json()), name


async def test_attention_is_client_scoped(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    clients = AsyncClientRepo(api_session)
    await clients.create(client_id="acme", name="Acme", countries=[])
    await clients.create(client_id="other", name="Other", countries=[])
    api_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-1111", client_id="acme", tech="Nginx", cisa_kev=True),
            TAWatchlistEntry(name="Qilin", client_id="acme"),
        ]
    )
    await api_session.flush()
    await _seed_actor_articles(api_session, 1)

    h = auth_header(role="analyst", client_ids=["acme", "other"])
    acme = (
        await api_client.get(
            "/api/dashboard/attention", params={"days": 7}, headers={**h, "X-Client-ID": "acme"}
        )
    ).json()
    other = (
        await api_client.get(
            "/api/dashboard/attention", params={"days": 7}, headers={**h, "X-Client-ID": "other"}
        )
    ).json()
    assert acme["kev_in_stack"] == 1 and acme["watchlist_hits"] == 1
    assert other["kev_in_stack"] == 0 and other["watchlist_hits"] == 0


async def test_attention_client_without_countries(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    await AsyncClientRepo(api_session).create(client_id="nocountry", name="N", countries=[])
    h = {**auth_header(client_ids=["nocountry"]), "X-Client-ID": "nocountry"}
    r = await api_client.get("/api/dashboard/attention", params={"days": 7}, headers=h)
    assert r.status_code == 200 and r.json()["ransomware_in_client_scope"] == 0
    m = await api_client.get("/api/dashboard/map", params={"days": 7}, headers=h)
    assert m.json()["client_countries"] == []


async def test_attention_pir_hit_counts_matching_article(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    await _seed_actor_articles(api_session, 1)
    await AsyncPIRRepo(api_session).create(
        {"title": "Qilin", "criteria": {"threat_actors": ["Qilin"]}, "start_date": _TODAY},
        client_id="default",
    )
    r = await api_client.get("/api/dashboard/attention", params={"days": 7}, headers=auth_header())
    assert r.json()["pir_hits"] == 1


async def test_attention_brief_headline_uses_real_trend(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    await _seed_actor_articles(api_session, 3)
    r = await api_client.get("/api/dashboard/attention", params={"days": 7}, headers=auth_header())
    assert r.json()["brief"]["headline"].startswith("Qilin")


async def test_map_combines_incidents_and_ransomware(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    a = await AsyncArticleRepo(api_session).upsert(
        url="https://example.com/sg",
        title="SG incident",
        source="S",
        posted_on=_TODAY,
        confirmed_incident=True,
    )
    await AsyncArticleRepo(api_session).set_enrichment(
        a, countries=[("SG", "victim")], threat_actors=["Qilin"]
    )
    api_session.add(
        RansomwareVictim(
            offset_key="qilin:acme:SG",
            group_name="qilin",
            victim="Acme",
            country_code="SG",
            published=_TODAY,
        )
    )
    await api_session.flush()
    r = await api_client.get("/api/dashboard/map", params={"days": 7}, headers=auth_header())
    points = r.json()["points"]
    assert len(points) == 1
    assert points[0]["country_code"] == "SG"
    assert points[0]["incidents"] == 1 and points[0]["ransomware_victims"] == 1
    assert points[0]["top_actor"] == "Qilin"


async def test_trending_all_time_label(api_client: AsyncClient, auth_header) -> None:
    r = await api_client.get("/api/dashboard/trending", headers=auth_header())
    assert r.json()["window_label"] == "7 hari terakhir vs 7 hari sebelumnya"


async def test_trending_daily_capped_to_31_buckets(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    await _seed_actor_articles(api_session, 3)
    r = await api_client.get(
        "/api/dashboard/trending", params={"days": 3650}, headers=auth_header()
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items and items[0]["count"] == 3
    assert all(len(i["daily"]) <= 31 for i in items)
    assert sum(items[0]["daily"]) == 3


async def test_dashboard_requires_auth(api_client: AsyncClient) -> None:
    assert (await api_client.get("/api/dashboard/map")).status_code == 401
