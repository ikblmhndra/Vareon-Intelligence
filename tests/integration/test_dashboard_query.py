"""Integration test `AsyncDashboardRepo` -- Postgres REAL (testcontainers).
Fase 7.3 (router `intelligence`/`exec_dashboard`/`recap`, Bagian 5)."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_TODAY = datetime.date.today()


async def _ensure_clients(session: AsyncSession) -> None:
    await AsyncClientRepo(session).ensure_default()


async def _seed_articles(session: AsyncSession) -> None:
    repo = AsyncArticleRepo(session)
    a1 = await repo.upsert(
        url="https://example.com/a1",
        title="Apt41 hits manufacturing",
        source="BleepingComputer",
        posted_on=_TODAY,
        news_type="Incident",
        confirmed_incident=True,
    )
    await repo.set_enrichment(
        a1,
        industries=["Manufacturing"],
        countries=[("US", "mentioned"), ("VN", "victim")],
        threat_actors=["Apt41"],
        ttps=[("T1059", "Command Scripting")],
    )

    a2 = await repo.upsert(
        url="https://example.com/a2",
        title="Vendor promo article",
        source="Wired",
        posted_on=_TODAY,
        news_type="Vendor Report Article",
    )
    await repo.set_enrichment(
        a2, industries=["Manufacturing", "Healthcare"], threat_actors=["Apt41"]
    )


async def test_count_articles_excludes_news_types(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_articles(async_db_session)
    repo = AsyncDashboardRepo(async_db_session)

    total = await repo.count_articles(
        posted_on_start=_TODAY, posted_on_end=None, exclude_news_types=None, confirmed_only=False
    )
    assert total == 2

    incidents_only = await repo.count_articles(
        posted_on_start=_TODAY,
        posted_on_end=None,
        exclude_news_types=["Vendor Report Article"],
        confirmed_only=False,
    )
    assert incidents_only == 1


async def test_monthly_industry_and_country_counts(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_articles(async_db_session)
    repo = AsyncDashboardRepo(async_db_session)

    industry_rows = await repo.monthly_industry_counts(
        posted_on_start=_TODAY, posted_on_end=None, exclude_news_types=None, confirmed_only=False
    )
    industries = {row[0] for row in industry_rows}
    assert industries == {"Manufacturing", "Healthcare"}

    victim_rows = await repo.monthly_country_counts(
        role="victim",
        posted_on_start=_TODAY,
        posted_on_end=None,
        exclude_news_types=None,
        confirmed_only=False,
    )
    assert [r[0] for r in victim_rows] == ["VN"]

    # Default (role=None) = role apa pun (QA BUG-B1), bukan cuma "mentioned".
    all_rows = await repo.monthly_country_counts(
        posted_on_start=_TODAY, posted_on_end=None, exclude_news_types=None, confirmed_only=False
    )
    assert sorted(r[0] for r in all_rows) == ["US", "VN"]


async def test_country_aggregates_count_any_role_once_per_article(
    async_db_session: AsyncSession,
) -> None:
    """QA BUG-B1: "Countries Mentioned"/exec trend/spike dulu cuma hitung role
    "mentioned". Sekarang role apa pun -- dan negara yang sama di DUA role
    dalam satu artikel (RU victim + actor) tetap dihitung SATU artikel."""
    await _ensure_clients(async_db_session)
    await _seed_articles(async_db_session)
    repo = AsyncArticleRepo(async_db_session)
    a3 = await repo.upsert(
        url="https://example.com/a3",
        title="RU group hits RU bank",
        source="Wired",
        posted_on=_TODAY,
        news_type="Incident",
    )
    await repo.set_enrichment(a3, countries=[("RU", "victim"), ("RU", "actor"), ("VN", "victim")])
    dash = AsyncDashboardRepo(async_db_session)
    f = {"posted_on_start": _TODAY, "posted_on_end": None}

    top = dict(await dash.top_countries(limit=10, **f))
    assert top == {"US": 1, "VN": 2, "RU": 1}
    assert await dash.unique_country_count(**f) == 3

    monthly = {c: n for c, _, n in await dash.monthly_country_counts(**f)}
    assert monthly == {"US": 1, "VN": 2, "RU": 1}

    daily = {
        e: n
        for _, e, n in await dash.daily_entity_counts(dimension="country", posted_on_start=_TODAY)
    }
    assert daily == {"US": 1, "VN": 2, "RU": 1}

    rows = await dash.risk_matrix_rows(posted_on_start=_TODAY)
    a3_row = next(r for r in rows if "RU" in r["countries"])
    assert sorted(a3_row["countries"]) == ["RU", "VN"]


async def test_top_threat_actors_and_unique_count(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_articles(async_db_session)
    repo = AsyncDashboardRepo(async_db_session)

    top = await repo.top_threat_actors(
        limit=10,
        posted_on_start=_TODAY,
        posted_on_end=None,
        exclude_news_types=None,
        confirmed_only=False,
    )
    assert top == [("Apt41", 2)]

    unique_count = await repo.unique_threat_actor_count(
        posted_on_start=_TODAY, posted_on_end=None, exclude_news_types=None, confirmed_only=False
    )
    assert unique_count == 1


async def test_ttp_counts(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_articles(async_db_session)
    repo = AsyncDashboardRepo(async_db_session)

    ttps = await repo.ttp_counts(
        limit=15,
        posted_on_start=_TODAY,
        posted_on_end=None,
        exclude_news_types=None,
        confirmed_only=False,
    )
    assert ttps == [("T1059", "Command Scripting", 1)]


async def test_daily_entity_counts_and_totals(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_articles(async_db_session)
    repo = AsyncDashboardRepo(async_db_session)

    by_actor = await repo.daily_entity_counts(dimension="threat_actor", posted_on_start=_TODAY)
    assert by_actor == [(_TODAY, "Apt41", 2)]

    totals = await repo.daily_totals(posted_on_start=_TODAY)
    assert totals == [(_TODAY, 2)]


async def test_daily_entity_counts_ttp_dimension(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_articles(async_db_session)
    repo = AsyncDashboardRepo(async_db_session)

    by_ttp = await repo.daily_entity_counts(dimension="ttp", posted_on_start=_TODAY)
    assert by_ttp == [(_TODAY, "T1059|Command Scripting", 1)]


async def test_get_trending_all_time_uses_7_day_window(async_db_session: AsyncSession) -> None:
    from cti_api.services.trending import get_trending

    await _ensure_clients(async_db_session)
    await _seed_articles(async_db_session)

    result = await get_trending(async_db_session, days=None)
    assert result["window_days"] == 7
    assert result["window_label"] == "7 hari terakhir vs 7 hari sebelumnya"


async def test_risk_matrix_rows(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_articles(async_db_session)
    repo = AsyncDashboardRepo(async_db_session)

    rows = await repo.risk_matrix_rows(posted_on_start=_TODAY - datetime.timedelta(days=60))
    assert len(rows) == 2
    a1_row = next(r for r in rows if "T1059" in r["ttps"])
    assert a1_row["industries"] == ["Manufacturing"]
    assert sorted(a1_row["countries"]) == ["US", "VN"]
    assert a1_row["threat_actors"] == ["Apt41"]


async def test_cve_tech_severity_breakdown_unscoped(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    async_db_session.add_all(
        [
            CveTracker(
                cve_id="CVE-2026-1111",
                client_id="default",
                tech="WordPress",
                cve_severity="CRITICAL",
            ),
            CveTracker(
                cve_id="CVE-2026-2222", client_id="default", tech="WordPress", cve_severity="HIGH"
            ),
        ]
    )
    await async_db_session.flush()

    repo = AsyncDashboardRepo(async_db_session)
    rows = await repo.cve_tech_severity_breakdown()
    wp = next(r for r in rows if r["tech"] == "WordPress")
    assert wp["total"] == 2
    assert wp["critical"] == 1
    assert wp["high"] == 1

    await AsyncCveFalsePositiveRepo(async_db_session).mark("CVE-2026-1111", "default")
    rows_excluded = await repo.cve_tech_severity_breakdown()
    wp2 = next(r for r in rows_excluded if r["tech"] == "WordPress")
    assert wp2["total"] == 1


async def test_critical_cves_filters_by_client_and_kev(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    async_db_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-3333", client_id="default", tech="nginx", cisa_kev=True),
            CveTracker(cve_id="CVE-2026-4444", client_id="default", tech="nginx", cisa_kev=False),
        ]
    )
    await async_db_session.flush()

    repo = AsyncDashboardRepo(async_db_session)
    rows = await repo.critical_cves(client_id="default")
    assert [r.cve_id for r in rows] == ["CVE-2026-3333"]


async def test_source_counts(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_articles(async_db_session)
    repo = AsyncDashboardRepo(async_db_session)

    rows = await repo.source_counts()
    assert dict(rows) == {"BleepingComputer": 1, "Wired": 1}
