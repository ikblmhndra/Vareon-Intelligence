"""Integration test query overview dashboard (peta, watchlist, eksposur CVE, ransomware) --
Postgres REAL (testcontainers)."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from cti_core.db.models.cve import CveTicket, CveTracker
from cti_core.db.models.entity import Entity, EntityMention
from cti_core.db.models.ransomware import RansomwareVictim
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from cti_core.db.repositories.ransomware import AsyncRansomwareVictimRepo
from cti_core.db.repositories.ta import AsyncTARepo
from sqlalchemy import update
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


async def test_cve_exposure_critical_uses_score_like_cve_stats(
    async_db_session: AsyncSession,
) -> None:
    """`open_critical` harus sama dengan bucket critical `/api/cve/stats` (cve_score >= 9.0),
    bukan label `cve_severity`."""
    await _ensure_clients(async_db_session)
    async_db_session.add_all(
        [
            CveTracker(
                cve_id="CVE-2026-0101",
                client_id="default",
                tech="nginx",
                cve_score=9.5,
                cve_severity="HIGH",
            ),
            CveTracker(
                cve_id="CVE-2026-0103",
                client_id="default",
                tech="nginx",
                cve_score=9.0,
                cve_severity=None,
            ),
            CveTracker(
                cve_id="CVE-2026-0102",
                client_id="default",
                tech="nginx",
                cve_score=8.0,
                cve_severity="CRITICAL",
            ),
        ]
    )
    await async_db_session.flush()
    counts = await AsyncDashboardRepo(async_db_session).cve_exposure_counts(
        client_id="default", tech=None, exclude_cve_ids=None
    )
    assert counts["open_critical"] == 2


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


async def test_ransomware_summary_top_n(async_db_session: AsyncSession) -> None:
    """`top_n` melebarkan daftar grup (dashboard 5, peta/attention tetap 3 default)."""
    counts = {"Akira": 3, "Bashe": 2, "Cactus": 2, "Dragon": 1, "Eldorado": 1, "Fog": 1}
    for group, n in counts.items():
        for i in range(n):
            async_db_session.add(
                RansomwareVictim(
                    offset_key=f"{group}-{i}",
                    group_name=group,
                    victim=f"{group}-{i}",
                    discovered=_TODAY,
                )
            )
    await async_db_session.flush()
    repo = AsyncRansomwareVictimRepo(async_db_session)
    since = _TODAY - datetime.timedelta(days=30)
    three = await repo.summary(since=since, apac_codes=(), client_codes=())
    assert three["top_groups"] == [("Akira", 3), ("Bashe", 2), ("Cactus", 2)]
    five = await repo.summary(since=since, apac_codes=(), client_codes=(), top_n=5)
    assert five["top_groups"] == [*three["top_groups"], ("Dragon", 1), ("Eldorado", 1)]


async def test_incident_country_profile_counts_any_role_once(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    a = await repo.upsert(
        url="https://example.com/r1",
        title="Multi role",
        source="S",
        posted_on=_TODAY,
        confirmed_incident=True,
    )
    await repo.set_enrichment(a, countries=[("ID", "victim"), ("ID", "mentioned"), ("SG", "actor")])
    rows = await AsyncDashboardRepo(async_db_session).incident_country_profile(posted_on_start=None)
    assert {(c, n) for c, n, _, _ in rows} == {("ID", 1), ("SG", 1)}


async def test_kev_tech_names_orders_by_count_and_skips_closed(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    rows = [("Nginx", 2), ("Apache", 1), ("Citrix", 1), ("Zimbra", 1)]
    n = 0
    for tech, count in rows:
        for _ in range(count):
            n += 1
            async_db_session.add(
                CveTracker(
                    cve_id=f"CVE-2026-7{n:03d}", client_id="default", tech=tech, cisa_kev=True
                )
            )
    async_db_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-7100", client_id="default", tech="Exchange", cisa_kev=True),
            CveTracker(cve_id="CVE-2026-7101", client_id="default", tech=None, cisa_kev=True),
            CveTracker(cve_id="CVE-2026-7102", client_id="default", tech="Redis", cisa_kev=False),
            CveTracker(cve_id="CVE-2026-7103", client_id="other", tech="Nginx", cisa_kev=True),
        ]
    )
    await async_db_session.flush()
    async_db_session.add(
        CveTicket(
            cve_id="CVE-2026-7100",
            client_id="default",
            ticket_id="CTI-2026-11-001",
            closure_date=_TODAY,
        )
    )
    await async_db_session.flush()
    repo = AsyncDashboardRepo(async_db_session)
    scope: dict[str, Any] = {"tech": None, "exclude_cve_ids": None}
    assert await repo.kev_tech_names(client_id="default", **scope) == ["Nginx", "Apache", "Citrix"]
    assert await repo.kev_tech_names(client_id="other", **scope) == ["Nginx"]


async def test_watchlist_top_names_scoped_to_client(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    ta = AsyncTARepo(async_db_session)
    await ta.add_to_watchlist("Qilin", "default")
    await ta.add_to_watchlist("Akira", "default")
    await ta.add_to_watchlist("LockBit", "other")
    repo = AsyncArticleRepo(async_db_session)
    for actor, n in (("Qilin", 2), ("Akira", 1), ("LockBit", 3)):
        for i in range(n):
            a = await repo.upsert(
                url=f"https://example.com/top-{actor}-{i}",
                title=f"{actor} {i}",
                source="S",
                posted_on=_TODAY,
            )
            await repo.set_enrichment(a, threat_actors=[actor])
    dash = AsyncDashboardRepo(async_db_session)
    assert await dash.watchlist_top_names(client_id="default", posted_on_start=None) == [
        "Qilin",
        "Akira",
    ]
    assert await dash.watchlist_top_names(client_id="other", posted_on_start=None) == ["LockBit"]
    tomorrow = _TODAY + datetime.timedelta(days=1)
    assert await dash.watchlist_top_names(client_id="default", posted_on_start=tomorrow) == []


async def test_ransomware_count_in_countries_window_is_half_open(
    async_db_session: AsyncSession,
) -> None:
    since = _TODAY - datetime.timedelta(days=14)
    until = _TODAY - datetime.timedelta(days=7)
    one = datetime.timedelta(days=1)
    for key, cc, d in (
        ("a", "SG", since - one),
        ("b", "SG", since),
        ("c", "SG", until - one),
        ("d", "SG", until),
        ("e", "US", since),
    ):
        async_db_session.add(
            RansomwareVictim(
                offset_key=key, group_name="Qilin", victim=key, country_code=cc, discovered=d
            )
        )
    await async_db_session.flush()
    repo = AsyncRansomwareVictimRepo(async_db_session)
    assert await repo.count_in_countries(since=since, until=until, codes={"SG"}) == 2
    assert await repo.count_in_countries(since=since, until=until, codes=()) == 0


async def test_ransomware_top_industry_ignores_blank(async_db_session: AsyncSession) -> None:
    repo = AsyncRansomwareVictimRepo(async_db_session)
    assert await repo.top_industry_in_countries(since=None, codes=()) is None
    for i, industry in enumerate(("Finance", "Finance", "Health", "", "   ", None)):
        async_db_session.add(
            RansomwareVictim(
                offset_key=f"i{i}",
                group_name="Qilin",
                victim=f"i{i}",
                country_code="SG",
                industry=industry,
                discovered=_TODAY,
            )
        )
    await async_db_session.flush()
    assert await repo.top_industry_in_countries(since=None, codes={"SG"}) == ("Finance", 2)
    assert await repo.top_industry_in_countries(since=None, codes=()) is None
    # Seri: nama menang secara alfabet.
    await async_db_session.execute(
        update(RansomwareVictim).where(RansomwareVictim.industry == "Finance").values(industry=None)
    )
    await async_db_session.execute(
        update(RansomwareVictim)
        .where(RansomwareVictim.offset_key == "i0")
        .values(industry="Energy")
    )
    assert await repo.top_industry_in_countries(since=None, codes={"SG"}) == ("Energy", 1)
    await async_db_session.execute(
        update(RansomwareVictim).where(RansomwareVictim.industry.is_not(None)).values(industry=" ")
    )
    assert await repo.top_industry_in_countries(since=None, codes={"SG"}) is None


async def test_daily_entity_counts_malware_and_cve(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    a = await repo.upsert(
        url="https://example.com/mal-1", title="Emotet", source="S", posted_on=_TODAY
    )
    await repo.set_enrichment(a, malware=[("Emotet", "malware"), ("Cobalt Strike", "tool")])
    cve = Entity(
        type="vulnerability",
        stix_id="vulnerability--cve-2026-1111",
        name="CVE-2026-1111",
        external_id="CVE-2026-1111",
        source="analyst",
    )
    async_db_session.add(cve)
    await async_db_session.flush()
    async_db_session.add(
        EntityMention(
            article_id=a.id, entity_id=cve.id, method="dictionary", matched_alias=cve.name
        )
    )
    await async_db_session.flush()
    dash = AsyncDashboardRepo(async_db_session)
    start = _TODAY - datetime.timedelta(days=1)
    end = _TODAY + datetime.timedelta(days=1)
    malware = await dash.daily_entity_counts(
        dimension="malware", posted_on_start=start, posted_on_end=end
    )
    assert {name for _d, name, _n in malware} == {"Emotet", "Cobalt Strike"}
    cves = await dash.daily_entity_counts(dimension="cve", posted_on_start=start, posted_on_end=end)
    assert [(name, n) for _d, name, n in cves] == [("CVE-2026-1111", 1)]
