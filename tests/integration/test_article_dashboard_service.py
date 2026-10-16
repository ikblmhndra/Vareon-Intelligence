"""Integration test `cti_api.services.article_dashboard` -- Postgres REAL
(testcontainers). Fase 7.4 Grup D -- `GET /api/dashboard`, endpoint yang
ketinggalan pas Fase 7.3 (blocker normalisasi negara, sekarang resolve)."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services import article_dashboard as svc
from cti_core.db.repositories.article import AsyncArticleRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_TODAY = datetime.date.today()


async def _seed(repo: AsyncArticleRepo) -> None:
    a1 = await repo.upsert(
        url="https://example.com/a1",
        title="Apt41 breaches manufacturing",
        source="GBHackers",
        posted_on=_TODAY,
        news_type="apac",
    )
    await repo.set_enrichment(
        a1,
        industries=["Manufacturing"],
        countries=[("ID", "mentioned"), ("US", "victim")],
        threat_actors=["Apt41"],
        ttps=[("T1059", "Command Scripting")],
    )

    a2 = await repo.upsert(
        url="https://example.com/a2",
        title="Zero trust best practices",
        source="Wired",
        posted_on=_TODAY,
        news_type="Security Technology & Best Practices",
    )
    await repo.set_enrichment(a2, industries=["Manufacturing"], countries=[("ID", "mentioned")])


async def test_get_dashboard_stats_aggregates_all_dimensions(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    await _seed(repo)
    svc._dashboard_cache.clear()

    result = await svc.get_dashboard_stats(async_db_session)
    assert result["total_articles"] == 2
    assert result["total_sources"] == 2
    # Role apa pun (QA BUG-B1): ID (mentioned) + US (victim).
    assert result["total_countries"] == 2
    assert result["total_threat_actors"] == 1

    top_industries = {i["name"]: i["count"] for i in result["top_industries"]}
    assert top_industries["Manufacturing"] == 2

    top_countries = {c["name"]: c["count"] for c in result["top_countries"]}
    assert top_countries == {"ID": 2, "US": 1}

    by_type = {t["name"]: t["count"] for t in result["by_news_type"]}
    assert by_type["apac"] == 1
    assert by_type["Security Technology & Best Practices"] == 1

    assert len(result["timeline"]) == 1
    assert result["timeline"][0]["date"] == _TODAY.isoformat()
    assert result["timeline"][0]["count"] == 2

    top_ttps = result["top_ttps"]
    assert any("T1059" in t["name"] for t in top_ttps)


async def test_get_dashboard_stats_filters_by_date_range(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    await _seed(repo)
    older = _TODAY - datetime.timedelta(days=10)
    await repo.upsert(
        url="https://example.com/old", title="Old article", source="Old", posted_on=older
    )
    svc._dashboard_cache.clear()

    result = await svc.get_dashboard_stats(async_db_session, posted_on_start=_TODAY)
    assert result["total_articles"] == 2


async def test_get_dashboard_stats_caches_result(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    await _seed(repo)
    svc._dashboard_cache.clear()

    first = await svc.get_dashboard_stats(async_db_session)
    assert first["total_articles"] == 2

    await repo.upsert(url="https://example.com/a3", title="A3", source="X", posted_on=_TODAY)
    cached = await svc.get_dashboard_stats(async_db_session)
    assert cached["total_articles"] == 2  # cache TTL 900s masih kepake
    svc._dashboard_cache.clear()


async def test_get_dashboard_stats_empty_db_returns_zeroes(async_db_session: AsyncSession) -> None:
    svc._dashboard_cache.clear()
    result = await svc.get_dashboard_stats(async_db_session)
    assert result["total_articles"] == 0
    assert result["top_countries"] == []
    assert result["timeline"] == []


async def _seed_periods(session: AsyncSession) -> None:
    """Jendela 7 hari: a1-a3 ada di dalamnya, a4 di periode sebelumnya
    (today-14 .. today-7), a5 di luar keduanya."""
    repo = AsyncArticleRepo(session)

    a1 = await repo.upsert(
        url="https://example.com/p1",
        title="Apt41 breaches manufacturing",
        source="S1",
        posted_on=_TODAY,
        news_type="apac",
    )
    await repo.set_enrichment(
        a1,
        industries=["Manufacturing"],
        countries=[("ID", "mentioned"), ("US", "victim")],
        threat_actors=["Apt41"],
        ttps=[("T1059", "Command Scripting")],
    )
    a1.confirmed_incident = True

    a2 = await repo.upsert(
        url="https://example.com/p2",
        title="Zero trust best practices",
        source="S2",
        posted_on=_TODAY,
        news_type="Security Technology & Best Practices",
    )
    await repo.set_enrichment(a2, industries=["General"], countries=[("ID", "mentioned")])

    a3 = await repo.upsert(
        url="https://example.com/p3",
        title="Broad campaign",
        source="S3",
        posted_on=_TODAY - datetime.timedelta(days=2),
        news_type="global",
    )
    await repo.set_enrichment(a3, industries=["General"])

    a4 = await repo.upsert(
        url="https://example.com/p4",
        title="Earlier incident",
        source="S4",
        posted_on=_TODAY - datetime.timedelta(days=10),
        news_type="apac",
    )
    a4.confirmed_incident = True

    await repo.upsert(
        url="https://example.com/p5",
        title="Way older",
        source="S5",
        posted_on=_TODAY - datetime.timedelta(days=30),
        news_type="global",
    )
    await session.flush()


async def test_get_dashboard_stats_days_compares_previous_period(
    async_db_session: AsyncSession,
) -> None:
    await _seed_periods(async_db_session)
    svc._dashboard_cache.clear()

    result = await svc.get_dashboard_stats(async_db_session, days=7)
    assert result["total_articles"] == 3
    assert result["prev_total_articles"] == 1  # p4 saja; p5 (today-30) di luar keduanya
    assert result["confirmed_incidents"] == 1
    assert result["prev_confirmed_incidents"] == 1
    assert result["generated_at"]

    # Tanpa `days` (all-time) gak ada pembanding.
    svc._dashboard_cache.clear()
    all_time = await svc.get_dashboard_stats(async_db_session)
    assert all_time["total_articles"] == 5
    assert all_time["prev_total_articles"] is None
    assert all_time["prev_confirmed_incidents"] is None
    assert all_time["confirmed_incidents"] == 2


async def test_get_dashboard_stats_incident_only_drops_non_incident_types(
    async_db_session: AsyncSession,
) -> None:
    await _seed_periods(async_db_session)
    svc._dashboard_cache.clear()

    result = await svc.get_dashboard_stats(async_db_session, days=7, incident_only=True)
    assert result["total_articles"] == 2  # p2 (Security Technology & Best Practices) keluar
    by_type = {t["name"] for t in result["by_news_type"]}
    assert "Security Technology & Best Practices" not in by_type
    assert result["coverage"]["with_country"] == 1  # country p2 ikut hilang
    assert result["industry_unspecified"] == 1  # tinggal p3


async def test_get_dashboard_stats_splits_general_industry_and_reports_coverage(
    async_db_session: AsyncSession,
) -> None:
    await _seed_periods(async_db_session)
    svc._dashboard_cache.clear()

    result = await svc.get_dashboard_stats(async_db_session, days=7)
    assert {i["name"] for i in result["top_industries"]} == {"Manufacturing"}
    assert result["industry_unspecified"] == 2  # p2 + p3
    assert result["coverage"] == {"with_country": 2, "with_actor": 1, "with_ttp": 1}
