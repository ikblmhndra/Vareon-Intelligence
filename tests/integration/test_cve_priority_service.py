"""Integration test `cti_api.services.cve_priority.prioritize_campaign_
cves` -- Postgres REAL (testcontainers). Fase 7.4 Grup A (2026-09-23)."""

from __future__ import annotations

import pytest
from cti_api.services import cve_priority as svc
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.techstack import TechStackEntry
from cti_core.db.repositories.auth import AsyncClientRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _ensure_clients(session: AsyncSession) -> None:
    await AsyncClientRepo(session).ensure_default()


async def test_prioritize_empty_list_returns_empty(async_db_session: AsyncSession) -> None:
    assert await svc.prioritize_campaign_cves(async_db_session, []) == []


async def test_prioritize_unknown_cve_gets_low_default(async_db_session: AsyncSession) -> None:
    result = await svc.prioritize_campaign_cves(async_db_session, ["CVE-2099-0001"])
    assert result[0]["priority_label"] == "low"
    assert result[0]["priority_score"] == 20
    assert result[0]["patch_urgency"] == "monitor"
    assert result[0]["cvss_score"] is None


async def test_prioritize_critical_kev_exploited_in_tech_stack_is_immediate(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    async_db_session.add(
        CveTracker(
            cve_id="CVE-2026-0001",
            client_id="default",
            tech="WordPress",
            cve_score=9.8,
            cve_severity="CRITICAL",
            cisa_kev=True,
            active_exploitation=True,
            poc_available=True,
        )
    )
    async_db_session.add(TechStackEntry(name="WordPress", client_id="default"))
    await async_db_session.flush()

    result = await svc.prioritize_campaign_cves(
        async_db_session, ["CVE-2026-0001"], client_id="default"
    )
    # 9.8*10*.3 + 100*.2(kev) + 100*.2(exploited) + 100*.1(poc) + 100*.2(tech_stack) = 99.4
    assert result[0]["priority_label"] == "critical_patch"
    assert result[0]["patch_urgency"] == "immediate"
    assert result[0]["in_tech_stack"] is True
    assert result[0]["priority_score"] == 99.4


async def test_prioritize_not_in_tech_stack_cannot_reach_critical_patch(
    async_db_session: AsyncSession,
) -> None:
    """Tech stack membership itu 20% bobot -- CVE score maksimum (9.8)
    + KEV + exploited + POC tanpa tech_stack cuma sampai 79.4, di bawah
    threshold `critical_patch` (80). Port formula apa adanya, bukan
    asumsi -- angka ini KETAUAN lewat ngitung, bukan ditebak."""
    await _ensure_clients(async_db_session)
    async_db_session.add(
        CveTracker(
            cve_id="CVE-2026-0002",
            client_id="default",
            tech="SomeOtherTech",
            cve_score=9.8,
            cve_severity="CRITICAL",
            cisa_kev=True,
            active_exploitation=True,
            poc_available=True,
        )
    )
    await async_db_session.flush()

    result = await svc.prioritize_campaign_cves(
        async_db_session, ["CVE-2026-0002"], client_id="default"
    )
    assert result[0]["in_tech_stack"] is False
    assert result[0]["priority_score"] == 79.4
    assert result[0]["priority_label"] == "high_priority"
    assert result[0]["patch_urgency"] == "7d"


async def test_prioritize_sorts_by_score_descending(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    async_db_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-0003", client_id="default", tech="A", cve_score=2.0),
            CveTracker(
                cve_id="CVE-2026-0004", client_id="default", tech="B", cve_score=9.8, cisa_kev=True
            ),
        ]
    )
    await async_db_session.flush()

    result = await svc.prioritize_campaign_cves(
        async_db_session, ["CVE-2026-0003", "CVE-2026-0004"], client_id="default"
    )
    assert [r["cve_id"] for r in result] == ["CVE-2026-0004", "CVE-2026-0003"]


async def test_prioritize_prefers_the_callers_own_tracker_row(
    async_db_session: AsyncSession,
) -> None:
    """CVE yang sama bisa punya baris per client dengan `tech` berbeda. `in_tech_stack` harus
    dihitung dari baris client yang bertanya, bukan baris client lain yang kebetulan terambil."""
    await AsyncClientRepo(async_db_session).ensure_default()
    await AsyncClientRepo(async_db_session).create(client_id="acme", name="Acme", countries=[])
    async_db_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-0005", client_id="acme", tech="Joomla", cve_score=5.0),
            CveTracker(
                cve_id="CVE-2026-0005", client_id="default", tech="WordPress", cve_score=5.0
            ),
            TechStackEntry(name="Joomla", client_id="acme"),
            TechStackEntry(name="WordPress", client_id="default"),
        ]
    )
    await async_db_session.flush()

    for client_id in ("acme", "default"):
        result = await svc.prioritize_campaign_cves(
            async_db_session, ["CVE-2026-0005"], client_id=client_id
        )
        assert result[0]["in_tech_stack"] is True, client_id


async def test_prioritize_does_not_match_by_substring(async_db_session: AsyncSession) -> None:
    """Dulu substring dua arah: tracker `go` dianggap ada di techstack berisi `google`."""
    await _ensure_clients(async_db_session)
    async_db_session.add_all(
        [
            TechStackEntry(name="google", client_id="default"),
            TechStackEntry(name="jira service management", client_id="default"),
            CveTracker(cve_id="CVE-2026-1001", client_id="default", tech="go", cve_score=5.0),
            CveTracker(cve_id="CVE-2026-1002", client_id="default", tech="jira", cve_score=5.0),
        ]
    )
    await async_db_session.flush()

    result = await svc.prioritize_campaign_cves(
        async_db_session, ["CVE-2026-1001", "CVE-2026-1002"], client_id="default"
    )

    assert {r["cve_id"]: r["in_tech_stack"] for r in result} == {
        "CVE-2026-1001": False,
        "CVE-2026-1002": True,
    }
