"""Integration test query overview dashboard (peta, watchlist, eksposur CVE, ransomware) --
Postgres REAL (testcontainers)."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.models.cve import CveTicket, CveTracker
from cti_core.db.models.ransomware import RansomwareVictim
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from cti_core.db.repositories.ransomware import AsyncRansomwareVictimRepo
from cti_core.db.repositories.ta import AsyncTARepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_TODAY = datetime.date.today()


async def _ensure_clients(session: AsyncSession) -> None:
    repo = AsyncClientRepo(session)
    await repo.ensure_default()
    if await repo.get("other") is None:
        await repo.create(client_id="other", name="Other", countries=[])


async def test_incident_country_profile_counts_confirmed_only(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    a1 = await repo.upsert(
        url="https://example.com/p1",
        title="Qilin hits bank",
        source="S",
        posted_on=_TODAY,
        confirmed_incident=True,
    )
    await repo.set_enrichment(
        a1,
        industries=["Finance", "General"],
        countries=[("ID", "victim")],
        threat_actors=["Qilin"],
    )
    a2 = await repo.upsert(
        url="https://example.com/p2",
        title="Rumour",
        source="S",
        posted_on=_TODAY,
        confirmed_incident=False,
    )
    await repo.set_enrichment(a2, countries=[("ID", "victim")], threat_actors=["Akira"])

    rows = await AsyncDashboardRepo(async_db_session).incident_country_profile(
        posted_on_start=_TODAY - datetime.timedelta(days=7)
    )
    assert rows == [("ID", 1, "Qilin", "Finance")]


async def test_watchlist_hits_scoped_to_client(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await AsyncTARepo(async_db_session).add_to_watchlist("Qilin", "default")
    repo = AsyncArticleRepo(async_db_session)
    a = await repo.upsert(
        url="https://example.com/w1", title="Qilin again", source="S", posted_on=_TODAY
    )
    await repo.set_enrichment(a, threat_actors=["qilin"])

    dash = AsyncDashboardRepo(async_db_session)
    assert await dash.watchlist_hit_count(client_id="default", posted_on_start=None) == 1
    assert await dash.watchlist_hit_count(client_id="other", posted_on_start=None) == 0


async def _seed_cves(session: AsyncSession) -> None:
    await _ensure_clients(session)
    session.add_all(
        [
            CveTracker(
                cve_id="CVE-2026-0001",
                client_id="default",
                tech="nginx",
                cisa_kev=True,
                cve_score=9.1,
                cve_severity="critical",
            ),
            CveTracker(
                cve_id="CVE-2026-0002",
                client_id="default",
                tech="nginx",
                cisa_kev=False,
                cve_score=9.8,
                cve_severity="CRITICAL",
            ),
            CveTracker(
                cve_id="CVE-2026-0003",
                client_id="default",
                tech="nginx",
                cisa_kev=True,
                cve_score=9.8,
                cve_severity="CRITICAL",
            ),
        ]
    )
    await session.flush()
    session.add(
        CveTicket(
            cve_id="CVE-2026-0003",
            client_id="default",
            ticket_id="CTI-2026-10-001",
            closure_date=_TODAY,
        )
    )
    await session.flush()


async def test_cve_exposure_orders_kev_first_and_skips_closed(
    async_db_session: AsyncSession,
) -> None:
    await _seed_cves(async_db_session)
    repo = AsyncDashboardRepo(async_db_session)
    rows = await repo.cve_exposure(client_id="default", tech=None, exclude_cve_ids=None)
    assert [c.cve_id for c, _ in rows] == ["CVE-2026-0001", "CVE-2026-0002"]
    assert all(t is None for _, t in rows)
    counts = await repo.cve_exposure_counts(client_id="default", tech=None, exclude_cve_ids=None)
    assert counts == {"open_critical": 2, "open_kev": 1, "kev_without_ticket": 1}


async def test_cve_exposure_tech_none_vs_empty(async_db_session: AsyncSession) -> None:
    await _seed_cves(async_db_session)
    repo = AsyncDashboardRepo(async_db_session)
    assert await repo.cve_exposure(client_id="default", tech=None, exclude_cve_ids=None)
    assert await repo.cve_exposure(client_id="default", tech=[], exclude_cve_ids=None) == []
    assert await repo.cve_exposure(client_id="default", tech=["nginx"], exclude_cve_ids=None)


async def test_tickets_closed_mean_days(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    created = datetime.datetime.combine(
        _TODAY - datetime.timedelta(days=10), datetime.time(12, 0), tzinfo=datetime.UTC
    )
    for i, days in enumerate((2, 4), start=1):
        async_db_session.add(
            CveTicket(
                cve_id=f"CVE-2026-010{i}",
                client_id="default",
                ticket_id=f"CTI-2026-10-90{i}",
                created_at=created,
                closure_date=created.date() + datetime.timedelta(days=days),
            )
        )
    await async_db_session.flush()
    got = await AsyncDashboardRepo(async_db_session).tickets_closed(
        client_id="default", since=_TODAY - datetime.timedelta(days=30)
    )
    assert got == (2, 3.0)


async def test_ransomware_summary_and_weekly(async_db_session: AsyncSession) -> None:
    for key, cc, d in (("a", "SG", _TODAY), ("b", "US", _TODAY), ("c", "SG", None)):
        async_db_session.add(
            RansomwareVictim(
                offset_key=key, group_name="Qilin", victim=key, country_code=cc, discovered=d
            )
        )
    await async_db_session.flush()
    repo = AsyncRansomwareVictimRepo(async_db_session)
    s = await repo.summary(
        since=_TODAY - datetime.timedelta(days=30), apac_codes={"SG"}, client_codes={"SG"}
    )
    assert (s["total"], s["apac"], s["client_scope"], s["undated"]) == (2, 1, 1, 1)
    assert s["top_groups"] == [("Qilin", 2)]
    assert s["by_country"] == {"SG": 1, "US": 1}
    weekly = await repo.weekly_counts(weeks=8)
    assert len(weekly) == 8
    assert weekly[-1][1] == 2
