"""Service overview dashboard: scope client (KEV/FP), PIR + periode -- Postgres REAL."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services.dashboard_overview import (
    get_attention,
    get_cve_exposure,
    get_map,
    get_ransomware,
)
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_TODAY = datetime.date.today()


async def test_attention_excludes_false_positive_and_applies_pir_period(
    async_db_session: AsyncSession,
) -> None:
    await AsyncClientRepo(async_db_session).ensure_default()
    async_db_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-0001", client_id="default", tech="Nginx", cisa_kev=True),
            CveTracker(cve_id="CVE-2026-0002", client_id="default", tech="Nginx", cisa_kev=True),
        ]
    )
    await async_db_session.flush()
    await AsyncCveFalsePositiveRepo(async_db_session).mark("CVE-2026-0002", "default")

    repo = AsyncArticleRepo(async_db_session)
    old = _TODAY - datetime.timedelta(days=40)
    await repo.upsert(
        url="https://example.com/old",
        title="Old Qilin",
        source="S",
        posted_on=old,
        confirmed_incident=True,
    )
    pir_repo = AsyncPIRRepo(async_db_session)
    await pir_repo.create(
        {"title": "Qilin", "criteria": {"threat_actors": ["Qilin"]}, "start_date": old},
        client_id="default",
    )

    out = await get_attention(async_db_session, client_id="default", days=7)
    assert out["kev_in_stack"] == 1
    assert out["kev_without_ticket"] == 1
    # Artikel hanya ada di luar periode 7 hari: PIR tidak boleh dihitung.
    assert out["pir_hits"] == 0
    assert out["brief"]["headline"] == "1 CVE KEV cocok dengan tech stack klien."


async def test_map_ransomware_and_cve_exposure_shapes(async_db_session: AsyncSession) -> None:
    await AsyncClientRepo(async_db_session).ensure_default()
    async_db_session.add(
        CveTracker(cve_id="CVE-2026-0009", client_id="default", tech="Nginx", cisa_kev=True)
    )
    await async_db_session.flush()

    m = await get_map(async_db_session, client_id="default", days=7)
    assert m["points"] == [] and m["client_countries"] == []
    r = await get_ransomware(async_db_session, days=None)
    assert len(r["weekly"]) == 8 and r["total"] == 0
    e = await get_cve_exposure(async_db_session, client_id="default", days=7)
    assert [i["cve_id"] for i in e["items"]] == ["CVE-2026-0009"]
    assert e["items"][0]["ticket_id"] is None and e["open_kev"] == 1


async def test_open_critical_skips_not_affected_and_resolved_tickets(
    async_db_session: AsyncSession,
) -> None:
    """Audit UI U6/U20: "open" = backlog CVE Dashboard, bukan "ticket belum ditutup"."""
    from cti_core.db.models.cve import CveTicket

    await AsyncClientRepo(async_db_session).ensure_default()
    async_db_session.add_all(
        [
            CveTracker(cve_id=f"CVE-2026-010{i}", client_id="default", tech="Nginx", cve_score=9.8)
            for i in range(4)
        ]
    )
    async_db_session.add_all(
        [
            CveTicket(
                cve_id="CVE-2026-0101",
                client_id="default",
                ticket_id="T-1",
                risk_acceptance="No Risk (Not Affected)",
            ),
            CveTicket(
                cve_id="CVE-2026-0102",
                client_id="default",
                ticket_id="T-2",
                remediation_status="Resolved",
            ),
            CveTicket(
                cve_id="CVE-2026-0103",
                client_id="default",
                ticket_id="T-3",
                remediation_status="Open",
            ),
        ]
    )
    await async_db_session.flush()

    e = await get_cve_exposure(async_db_session, client_id="default", days=7)
    # 0100 tanpa ticket + 0103 ticket Open; 0101 Not Affected dan 0102 Resolved bukan beban lagi.
    assert e["open_critical"] == 2


async def test_attention_brief_follows_incident_only(async_db_session: AsyncSession) -> None:
    """Audit UI U2: brief memakai toggle yang sama dengan kartu KPI."""
    from cti_api.services import dashboard_overview, trending

    dashboard_overview._CACHE.clear()
    trending._CACHE.clear()
    await AsyncClientRepo(async_db_session).ensure_default()
    repo = AsyncArticleRepo(async_db_session)
    for i, news_type in enumerate(("global", "Security Technology & Best Practices")):
        await repo.upsert(
            url=f"https://example.com/inc-{i}",
            title=f"Incident {i}",
            source="S",
            posted_on=_TODAY,
            confirmed_incident=True,
            news_type=news_type,
        )

    everything = await get_attention(async_db_session, client_id="default", days=7)
    threat_news = await get_attention(
        async_db_session, client_id="default", days=7, incident_only=True
    )
    assert everything["brief"]["detail"].startswith("2 insiden terkonfirmasi")
    assert threat_news["brief"]["detail"].startswith("1 insiden terkonfirmasi")


async def test_trending_without_a_usable_baseline_claims_no_rise(
    async_db_session: AsyncSession,
) -> None:
    """Audit UI U4: periode pembanding kosong -> tidak ada "baru"/persen, label jujur."""
    from cti_api.services import trending

    trending._CACHE.clear()
    repo = AsyncArticleRepo(async_db_session)
    for i in range(3):
        await repo.upsert(
            url=f"https://example.com/ttp-{i}",
            title=f"Exploit {i}",
            source="S",
            posted_on=_TODAY,
            ttps=[("T1190", "Exploit Public-Facing Application")],
        )

    out = await trending.get_trending(async_db_session, days=7)
    assert out["baseline_reliable"] is False
    assert "pembanding belum cukup data" in out["window_label"]
    [item] = [i for i in out["items"] if i["ttp_id"] == "T1190"]
    assert (item["is_new"], item["change_pct"], item["count"]) == (False, None, 3)
