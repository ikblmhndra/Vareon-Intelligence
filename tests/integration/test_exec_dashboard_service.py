"""Integration test `cti_api.services.exec_dashboard`/`spike`/
`risk_matrix` -- Postgres REAL (testcontainers). Fase 7.3 (router
`exec_dashboard`/`intelligence`, Bagian 5)."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services import exec_dashboard as exec_dashboard_service
from cti_api.services import risk_matrix as risk_matrix_service
from cti_api.services import spike as spike_service
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.indicator import Indicator
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_TODAY = datetime.date.today()


async def _ensure_clients(session: AsyncSession) -> None:
    await AsyncClientRepo(session).ensure_default()


async def _seed_incident_article(
    session: AsyncSession,
    *,
    url: str,
    industries: list[str],
    actors: list[str],
    posted_on: datetime.date,
) -> None:
    repo = AsyncArticleRepo(session)
    a = await repo.upsert(
        url=url,
        title=f"incident at {url}",
        source="BleepingComputer",
        posted_on=posted_on,
        news_type="Incident",
        confirmed_incident=True,
    )
    await repo.set_enrichment(a, industries=industries, threat_actors=actors)


async def test_get_exec_dashboard_v1_basic_shape(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_incident_article(
        async_db_session,
        url="https://x.com/1",
        industries=["Manufacturing"],
        actors=["Apt41"],
        posted_on=_TODAY,
    )
    async_db_session.add(
        CveTracker(
            cve_id="CVE-2026-5555", client_id="default", tech="nginx", cve_severity="CRITICAL"
        )
    )
    await async_db_session.flush()

    result = await exec_dashboard_service.get_exec_dashboard(async_db_session, days=90)
    assert result["total_incidents"] == 1
    assert result["ta_leaderboard"] == [{"name": "Apt41", "count": 1}]
    assert result["top_sectors"] == ["Manufacturing"]
    wp = next(r for r in result["cve_exposure"] if r["tech"] == "nginx")
    assert wp["critical"] == 1


async def test_get_exec_dashboard_v2_includes_tier2_and_role_sections(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    await _seed_incident_article(
        async_db_session,
        url="https://x.com/2",
        industries=["Manufacturing"],
        actors=["Apt41"],
        posted_on=_TODAY,
    )
    async_db_session.add(
        CveTracker(
            cve_id="CVE-2026-6666", client_id="default", tech="nginx", cisa_kev=True, cve_score=9.8
        )
    )
    await async_db_session.flush()

    result = await exec_dashboard_service.get_exec_dashboard_v2(
        async_db_session, days=90, client_id="default", role="soc"
    )
    assert "sector_risk_scores" in result
    assert "ta_velocity" in result
    assert result["view_config"]["sections"]["critical_cve_feed"] is True
    assert any(c["cve_id"] == "CVE-2026-6666" for c in result["critical_cves"])
    # role "soc" -- `cluster_list` section gak aktif (lihat
    # `build_view_config`), jadi `_get_recent_clusters()` gak kepanggil
    # sama sekali di test ini (bukan lagi karena deferred stub, Fase
    # 7.4 Grup A -- lihat test_exec_dashboard_recent_clusters_* di bawah
    # buat cakupan `cluster_list` role "analyst"/admin beneran).
    assert result["recent_clusters_summary"] == []


async def test_exec_dashboard_recent_clusters_populated_for_analyst_role(
    async_db_session: AsyncSession,
) -> None:
    """Fase 7.4 Grup A -- `cluster_list` aktif buat role "analyst",
    `_get_recent_clusters()` manggil `campaign.get_recent_campaigns()`
    beneran sekarang."""
    await _ensure_clients(async_db_session)
    repo = AsyncArticleRepo(async_db_session)
    titles = [
        "Apt41 threat group breaches manufacturing networks alpha",
        "Apt41 threat group breaches manufacturing networks beta",
    ]
    for i, title in enumerate(titles):
        a = await repo.upsert(
            url=f"https://example.com/cluster-{i}", title=title, source=f"S{i}", posted_on=_TODAY
        )
        await repo.set_enrichment(a, threat_actors=["Apt41"])

    result = await exec_dashboard_service.get_exec_dashboard_v2(
        async_db_session, days=90, client_id="default", role="analyst"
    )
    assert result["view_config"]["sections"]["cluster_list"] is True
    assert len(result["recent_clusters_summary"]) == 1
    assert result["recent_clusters_summary"][0]["threat_actors"] == ["Apt41"]


async def test_pending_fp_queue_includes_ioc_id(async_db_session: AsyncSession) -> None:
    """Fase 8 Grup F -- `id` wajib ada di row biar frontend bisa manggil
    kontrak baru `POST /api/iocs/{ioc_id}/feedback` (bukan kontrak lama
    `POST /api/iocs/feedback` yang legacy `exec.js` masih pakai, gap #7
    docs/PROGRESS.md)."""
    await _ensure_clients(async_db_session)
    ioc = Indicator(type="ip", value="203.0.113.5", confidence_score=55)
    async_db_session.add(ioc)
    await async_db_session.flush()

    result = await exec_dashboard_service.get_exec_dashboard_v2(
        async_db_session, days=90, client_id="default", role="analyst"
    )
    assert result["view_config"]["sections"]["fp_feedback_queue"] is True
    row = next(r for r in result["pending_fp_queue"] if r["value"] == "203.0.113.5")
    assert row["id"] == ioc.id


async def test_build_view_config_role_gating() -> None:
    analyst = exec_dashboard_service.build_view_config("analyst")
    soc = exec_dashboard_service.build_view_config("soc")
    admin = exec_dashboard_service.build_view_config("admin")

    assert analyst["sections"]["fp_feedback_queue"] is True
    assert soc["sections"]["fp_feedback_queue"] is False
    assert admin["sections"]["fp_feedback_queue"] is True
    assert soc["sections"]["critical_cve_feed"] is True


async def test_get_spikes_detects_recent_surge(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    baseline_start = _TODAY - datetime.timedelta(days=20)
    for i in range(10):
        await _seed_incident_article(
            async_db_session,
            url=f"https://x.com/baseline/{i}",
            industries=["Manufacturing"],
            actors=["QuietActor"],
            posted_on=baseline_start + datetime.timedelta(days=i),
        )
    for i in range(8):
        await _seed_incident_article(
            async_db_session,
            url=f"https://x.com/surge/{i}",
            industries=["Manufacturing"],
            actors=["QuietActor"],
            posted_on=_TODAY,
        )

    result = await spike_service.get_spikes(async_db_session, lookback_days=30, z_threshold=1.5)
    actor_spikes = {s["entity"]: s for s in result["threat_actors"]}
    assert "QuietActor" in actor_spikes
    assert actor_spikes["QuietActor"]["count"] == 8


async def test_get_risk_matrix_scores_high_activity_cell(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncArticleRepo(async_db_session)
    for i in range(4):
        a = await repo.upsert(
            url=f"https://x.com/matrix/{i}",
            title=f"matrix article {i}",
            source="s",
            posted_on=_TODAY,
        )
        await repo.set_enrichment(
            a,
            industries=["Manufacturing"],
            countries=[("US", "mentioned")],
            threat_actors=["Apt41", "Lazarus"],
            ttps=[("T1059", "Command Scripting")],
        )

    result = await risk_matrix_service.get_risk_matrix(async_db_session, days=30, compare_days=30)
    cell = next(
        r for r in result["matrix"] if r["industry"] == "Manufacturing" and r["country"] == "US"
    )
    assert cell["risk_score"] == 100
    assert set(cell["top_actors"]) == {"Apt41", "Lazarus"}


async def test_exec_dashboard_leaves_general_out_of_sector_views(
    async_db_session: AsyncSession,
) -> None:
    """ "General" = tanpa sektor spesifik (62% artikel di prod), bukan sektor: gak ikut peringkat,
    heatmap, jumlah sektor aktif, dan spike; jumlahnya dilaporkan lewat `sector_unspecified`."""
    await _ensure_clients(async_db_session)
    for i in range(2):
        await _seed_incident_article(
            async_db_session,
            url=f"https://x.com/general/{i}",
            industries=["General"],
            actors=[],
            posted_on=_TODAY,
        )
    await _seed_incident_article(
        async_db_session,
        url="https://x.com/manufacturing",
        industries=["Manufacturing"],
        actors=[],
        posted_on=_TODAY,
    )

    result = await exec_dashboard_service.get_exec_dashboard_v2(
        async_db_session, days=30, client_id="default", role="analyst"
    )
    assert result["total_incidents"] == 3
    assert result["top_sectors"] == ["Manufacturing"]
    assert [r["sector"] for r in result["sector_risk_scores"]] == ["Manufacturing"]
    assert [h["sector"] for h in result["sector_heatmap"]] == ["Manufacturing"]
    assert result["active_sectors"] == 1
    assert result["sector_unspecified"] == 2
    assert all(sp["entity"] != "General" for sp in result["industry_spikes"])


async def test_exec_dashboard_active_sectors_is_not_capped_at_top_8(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    for i in range(10):
        await _seed_incident_article(
            async_db_session,
            url=f"https://x.com/sector/{i}",
            industries=[f"Sector {i}"],
            actors=[],
            posted_on=_TODAY,
        )

    result = await exec_dashboard_service.get_exec_dashboard(async_db_session, days=30)
    assert len(result["top_sectors"]) == 8  # tampilan tetap top-8
    assert result["active_sectors"] == 10  # KPI = jumlah sebenarnya


async def test_exec_dashboard_prev_period_reliable_needs_half_the_days_covered(
    async_db_session: AsyncSession,
) -> None:
    """Periode pembanding dianggap andal bila >= separuh harinya punya artikel -- 3 artikel nyasar
    di jendela 30 hari sebelumnya bukan "ada data" (kasus prod: delta "↑32767%")."""
    await _ensure_clients(async_db_session)
    prev_start = _TODAY - datetime.timedelta(days=59)  # jendela sebelumnya: today-60 .. today-31
    for i in range(14):  # 14 hari < 15 (= 30 * 0.5)
        await _seed_incident_article(
            async_db_session,
            url=f"https://x.com/prev/{i}",
            industries=["Manufacturing"],
            actors=[],
            posted_on=prev_start + datetime.timedelta(days=i),
        )

    sparse = await exec_dashboard_service.get_exec_dashboard(async_db_session, days=30)
    assert sparse["prev_total"] == 14
    assert sparse["prev_period_reliable"] is False

    await _seed_incident_article(
        async_db_session,
        url="https://x.com/prev/14",
        industries=["Manufacturing"],
        actors=[],
        posted_on=prev_start + datetime.timedelta(days=14),
    )
    covered = await exec_dashboard_service.get_exec_dashboard(async_db_session, days=30)
    assert covered["prev_period_reliable"] is True


async def test_exec_dashboard_v2_reports_fp_queue_depth_and_volume_only_risk(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    for i, score in enumerate([45, 60, 90]):  # antrean = skor 40..74 -> 2 dari 3
        async_db_session.add(
            Indicator(type="ip", value=f"203.0.113.{i + 10}", confidence_score=score)
        )
    await _seed_incident_article(
        async_db_session,
        url="https://x.com/one",
        industries=["Manufacturing"],
        actors=[],
        posted_on=_TODAY,
    )
    await async_db_session.flush()

    analyst = await exec_dashboard_service.get_exec_dashboard_v2(
        async_db_session, days=90, client_id="default", role="analyst"
    )
    assert analyst["pending_fp_total"] == 2
    assert analyst["risk_volume_only"] is True  # belum ada >= 2 bulan riwayat yang cukup data

    soc = await exec_dashboard_service.get_exec_dashboard_v2(
        async_db_session, days=90, client_id="default", role="soc"
    )
    assert soc["pending_fp_total"] == 0  # section FP tidak aktif untuk role soc
