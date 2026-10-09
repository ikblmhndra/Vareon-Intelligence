"""KPI Exec "Critical CVEs" dan "KEV CVEs": total UTUH, severity dan KEV dihitung terpisah.

Dulu kartu "Critical CVEs" menjumlah `critical` dari `cve_exposure_v2`, yang dibatasi 10 tech
teratas (`cve_tech_severity_breakdown(limit=10)`): angkanya mengecil bila lebih dari 10 tech
punya CVE critical, dan keterangannya "cisa_kev flagged" padahal angkanya severity, bukan KEV.
`cve_kpi_counts` menghitung keduanya tanpa batas tech: critical = severity CRITICAL (huruf
besar/kecil sama), KEV = `cisa_kev` di SEMUA severity (arti "known exploited"). Cakupannya sama
dengan tabel exposure: lintas client (tanpa filter `client_id`), dan baris yang ditandai FP oleh
clientnya sendiri tidak dihitung."""

from __future__ import annotations

import pytest
from cti_api.services import exec_dashboard as exec_dashboard_service
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _clients(session: AsyncSession) -> None:
    clients = AsyncClientRepo(session)
    await clients.ensure_default()
    await clients.create(client_id="acme", name="Acme", countries=[])


def _cve(
    cve_id: str, tech: str, severity: str, *, kev: bool = False, client_id: str = "default"
) -> CveTracker:
    return CveTracker(
        cve_id=cve_id, client_id=client_id, tech=tech, cve_severity=severity, cisa_kev=kev
    )


async def test_critical_and_kev_are_counted_separately(async_db_session: AsyncSession) -> None:
    await _clients(async_db_session)
    async_db_session.add_all(
        [
            _cve("CVE-2026-0001", "nginx", "CRITICAL", kev=True),  # critical dan KEV
            _cve("CVE-2026-0002", "nginx", "critical"),  # critical saja (huruf kecil)
            _cve("CVE-2026-0003", "redis", "HIGH", kev=True),  # KEV saja: severity bukan critical
            _cve("CVE-2026-0004", "redis", "MEDIUM"),  # bukan keduanya
        ]
    )
    await async_db_session.flush()

    counts = await AsyncDashboardRepo(async_db_session).cve_kpi_counts()

    assert counts == {"critical": 2, "kev": 2}


async def test_rows_marked_false_positive_by_their_own_client_are_not_counted(
    async_db_session: AsyncSession,
) -> None:
    await _clients(async_db_session)
    async_db_session.add_all(
        [
            _cve("CVE-2026-0010", "nginx", "CRITICAL", kev=True, client_id="default"),
            _cve("CVE-2026-0010", "nginx", "CRITICAL", kev=True, client_id="acme"),
            _cve("CVE-2026-0011", "nginx", "CRITICAL", kev=True, client_id="default"),
        ]
    )
    await async_db_session.flush()
    fp = AsyncCveFalsePositiveRepo(async_db_session)
    await fp.mark("CVE-2026-0010", "default")  # baris acme masih valid
    await fp.mark("CVE-2026-0011", "default")  # satu-satunya baris: hilang

    counts = await AsyncDashboardRepo(async_db_session).cve_kpi_counts()

    assert counts == {"critical": 1, "kev": 1}


async def test_totals_are_not_truncated_to_the_ten_techs_of_the_exposure_table(
    async_db_session: AsyncSession,
) -> None:
    await _clients(async_db_session)
    async_db_session.add_all(
        _cve(f"CVE-2026-{i:04d}", f"tech{i:02d}", "CRITICAL", kev=i % 2 == 0) for i in range(1, 13)
    )
    await async_db_session.flush()
    repo = AsyncDashboardRepo(async_db_session)

    table = await repo.cve_tech_severity_breakdown(limit=10)

    assert sum(r["critical"] for r in table) == 10  # tabel exposure memang 10 tech teratas
    assert await repo.cve_kpi_counts() == {"critical": 12, "kev": 6}


async def test_no_cves_gives_zero_not_none(async_db_session: AsyncSession) -> None:
    await _clients(async_db_session)

    counts = await AsyncDashboardRepo(async_db_session).cve_kpi_counts()

    assert counts == {"critical": 0, "kev": 0}


async def test_exec_dashboard_v2_exposes_the_totals(async_db_session: AsyncSession) -> None:
    await _clients(async_db_session)
    async_db_session.add_all(
        [
            _cve("CVE-2026-0020", "nginx", "CRITICAL", kev=True),
            _cve("CVE-2026-0021", "redis", "CRITICAL"),
            _cve("CVE-2026-0022", "redis", "LOW"),
        ]
    )
    await async_db_session.flush()

    result = await exec_dashboard_service.get_exec_dashboard_v2(
        async_db_session, days=90, client_id="default", role="analyst"
    )

    assert result["cve_kpis"] == {"critical": 2, "kev": 1}
