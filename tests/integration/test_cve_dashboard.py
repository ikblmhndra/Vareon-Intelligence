"""Integration test `GET /api/cve/dashboard` -- Postgres REAL (testcontainers), lewat
HTTP (`api_client`): routing, auth, scope per-client, query SQL `list_dashboard_rows`/
`list_detected_years`, dan serialisasi `response_model` kepake semua.

Logika metrik-nya sendiri dites murni di `tests/unit/test_cve_dashboard.py`; di
sini yang dijaga: scope data (client lain, false-positive, techstack, tahun) dan
bahwa kolom hasil join benar-benar sampai ke hitungan."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

import pytest
from cti_core.db.models.cve import CveTicket, CveTracker
from cti_core.db.models.techstack import TechStackEntry
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion

pytestmark = pytest.mark.asyncio

UTC = datetime.UTC


def _cve(cve_id: str, **kw: Any) -> CveTracker:
    base: dict[str, Any] = {
        "client_id": "default",
        "tech": "WordPress",
        "cve_score": 7.5,
        "cve_severity": "HIGH",
        "solutions": "Upgrade to 2.0",
        # 03:00 UTC = 10:00 WIB
        "detected_on": datetime.datetime(2026, 9, 2, 3, 0, tzinfo=UTC),
        "published": datetime.date(2026, 9, 1),
    }
    base.update(kw)
    return CveTracker(cve_id=cve_id, **base)


def _ticket(cve_id: str, ticket_id: str, **kw: Any) -> CveTicket:
    return CveTicket(
        cve_id=cve_id, client_id=kw.pop("client_id", "default"), ticket_id=ticket_id, **kw
    )


async def _seed(session: AsyncSession) -> None:
    clients = AsyncClientRepo(session)
    await clients.ensure_default()
    await clients.create(client_id="acme", name="Acme", countries=[])
    session.add_all(
        [
            TechStackEntry(name="WordPress", client_id="default"),
            TechStackEntry(name="nginx", client_id="default"),
        ]
    )
    session.add_all(
        [
            # di-ack 2026-09-04 (WIB) -> MTTA 2 hari, MTTD 1 hari
            _cve("CVE-2026-7101", cve_score=9.8, cve_severity="CRITICAL"),
            # Not Affected: MTTR tidak dihitung walau actual_remediation_date terisi
            _cve(
                "CVE-2026-7102",
                tech="nginx",
                published=datetime.date(2026, 9, 5),
                detected_on=datetime.datetime(2026, 9, 5, 3, 0, tzinfo=UTC),
            ),
            # belum disentuh analis sama sekali
            _cve(
                "CVE-2026-7103",
                tech="nginx",
                cve_score=3.1,
                cve_severity="LOW",
                solutions="No solution yet",
                published=datetime.date(2026, 9, 8),
                detected_on=datetime.datetime(2026, 9, 10, 3, 0, tzinfo=UTC),
            ),
            # Resolved: MTTA 1, MTTR 5
            _cve(
                "CVE-2026-7104",
                cve_score=5.5,
                cve_severity="MEDIUM",
                published=datetime.date(2026, 1, 10),
                detected_on=datetime.datetime(2026, 1, 15, 3, 0, tzinfo=UTC),
            ),
            # false-positive -> tidak boleh ikut
            _cve("CVE-2026-7105", tech="nginx"),
            # tech di luar techstack -> tidak boleh ikut
            _cve("CVE-2026-7106", tech="Redis"),
            # client lain -> tidak boleh ikut
            _cve("CVE-2026-7107", client_id="acme"),
            # tahun lain: cuma muncul dengan ?year=2025 dan di daftar `years`
            _cve(
                "CVE-2025-7108",
                published=datetime.date(2025, 6, 1),
                detected_on=datetime.datetime(2025, 6, 2, 3, 0, tzinfo=UTC),
            ),
        ]
    )
    await session.flush()
    session.add_all(
        [
            _ticket(
                "CVE-2026-7101",
                "CTI-2026-09-001",
                owner_team="SOC",
                remediation_status="In Progress",
                acknowledged_by="analyst1",
                acknowledge_time=datetime.datetime(2026, 9, 4, 3, 0, tzinfo=UTC),
            ),
            _ticket(
                "CVE-2026-7102",
                "CTI-2026-09-002",
                owner_team="SOC",
                risk_acceptance="No Risk (Not Affected)",
                actual_remediation_date=datetime.date(2026, 9, 30),
                acknowledged_by="analyst1",
                acknowledge_time=datetime.datetime(2026, 9, 5, 4, 0, tzinfo=UTC),
            ),
            _ticket(
                "CVE-2026-7104",
                "CTI-2026-01-001",
                owner_team="Network Security",
                remediation_status="Resolved",
                actual_remediation_date=datetime.date(2026, 1, 20),
                acknowledged_by="analyst2",
                acknowledge_time=datetime.datetime(2026, 1, 16, 3, 0, tzinfo=UTC),
            ),
        ]
    )
    await AsyncCveFalsePositiveRepo(session).mark("CVE-2026-7105", "default")
    await session.flush()


async def test_dashboard_scopes_and_computes_from_real_rows(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed(api_session)
    resp = await api_client.get("/api/cve/dashboard?year=2026", headers=auth_header())
    assert resp.status_code == 200
    d = resp.json()

    assert d["year"] == 2026
    assert d["years"] == [2026, 2025]
    assert d["timezone"] == "Asia/Jakarta"

    # 7101-7104; 7105 (FP), 7106 (di luar techstack), 7107 (client lain), 7108 (2025) tidak ikut
    assert d["summary"]["total"] == 4
    assert (d["summary"]["critical"], d["summary"]["high"]) == (1, 1)
    assert (d["summary"]["medium"], d["summary"]["low"]) == (1, 1)
    assert d["summary"]["acknowledged"] == 3
    assert d["summary"]["no_solution_yet"] == 1

    assert d["status"] == {
        "unacknowledged": 1,
        "awaiting_status": 0,
        "open": 0,
        "in_progress": 1,
        "risk_accepted": 0,
        "completed": 1,
        "not_affected": 1,
    }
    assert d["summary"]["actionable"] == 3
    assert d["summary"]["resolution_rate"] == round(1 / 3, 4)

    # MTTD: 1, 0, 2, 5 | MTTA: 2, 0, 1 | MTTR: cuma 7104 (7102 Not Affected dibuang)
    assert (d["mttd"]["n"], d["mttd"]["mean"]) == (4, 2.0)
    assert (d["mtta"]["n"], d["mtta"]["mean"], d["mtta"]["max"]) == (3, 1.0, 2.0)
    assert (d["mttr"]["n"], d["mttr"]["mean"]) == (1, 5.0)

    teams = {t["team"]: t["count"] for t in d["by_team"]}
    assert teams == {"SOC": 2, "Network Security": 1, "Unassigned": 1}
    assert d["by_team"][-1]["team"] == "Unassigned"

    jan, sep = d["monthly"][0], d["monthly"][8]
    assert (jan["total"], jan["completed"], jan["mttr_mean"]) == (1, 1, 5.0)
    assert (sep["total"], sep["not_affected"], sep["in_progress"]) == (3, 1, 1)

    assert d["slowest"][0]["cve_id"] == "CVE-2026-7104"
    assert d["slowest"][0]["status"] == "completed"
    assert d["slowest"][0]["detected_on"] == "2026-01-15 10:00"


async def test_dashboard_other_year_and_client_scope(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed(api_session)
    resp = await api_client.get("/api/cve/dashboard?year=2025", headers=auth_header())
    assert resp.json()["summary"]["total"] == 1

    # client "acme" tanpa techstack: tidak ada filter tech, cuma CVE miliknya sendiri
    resp = await api_client.get(
        "/api/cve/dashboard?year=2026", headers={**auth_header(), "X-Client-ID": "acme"}
    )
    body = resp.json()
    assert body["summary"]["total"] == 1
    assert body["years"] == [2026]


async def test_dashboard_defaults_to_latest_year_with_data(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """Tanpa `year`: tahun berjalan kalau punya data, kalau tidak tahun terbaru yang ada."""
    await AsyncClientRepo(api_session).create(client_id="old", name="Old", countries=[])
    api_session.add(
        _cve(
            "CVE-2025-7201",
            client_id="old",
            detected_on=datetime.datetime(2025, 3, 3, 3, 0, tzinfo=UTC),
        )
    )
    await api_session.flush()
    resp = await api_client.get(
        "/api/cve/dashboard", headers={**auth_header(), "X-Client-ID": "old"}
    )
    assert resp.status_code == 200
    assert resp.json()["year"] == 2025
    assert resp.json()["summary"]["total"] == 1


async def test_dashboard_empty_client_returns_zeroed_payload(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/cve/dashboard?year=2026", headers=auth_header())
    assert resp.status_code == 200
    d = resp.json()
    assert d["summary"]["total"] == 0
    assert d["summary"]["resolution_rate"] is None
    assert d["years"] == []
    assert len(d["monthly"]) == 12


async def test_dashboard_requires_auth_and_valid_year(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    assert (await api_client.get("/api/cve/dashboard")).status_code == 401
    bad = await api_client.get("/api/cve/dashboard?year=1999", headers=auth_header())
    assert bad.status_code == 422


async def test_dashboard_response_shape(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed(api_session)
    resp = await api_client.get("/api/cve/dashboard?year=2026", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot
