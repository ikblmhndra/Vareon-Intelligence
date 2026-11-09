"""Integration test `AsyncMonitoredPackageRepo`/`AsyncPackageVulnRepo`/
`AsyncPackageDepGraphRepo` + service CRUD `cti_api.services.pkg_vuln` --
Postgres REAL (testcontainers). Fase 7.3 (router `pkg_vuln`, Bagian 4).

Panggilan HTTP eksternal (`_package_exists_on_registry`/`_fetch_osv_vulns`/
dst) di-mock `unittest.mock.patch` di sini (sama pola kayak
`tests/unit/test_mailer.py`) -- verifikasi LIVE terhadap osv.dev/deps.dev
beneran dilakuin terpisah (skrip manual), bukan bagian suite otomatis ini
(network flaky gak cocok buat CI)."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import pytest
from cti_api.services import pkg_vuln as pkg_vuln_service
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.package import MonitoredPackage
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.package import (
    AsyncMonitoredPackageRepo,
    AsyncPackageDepGraphRepo,
    AsyncPackageVulnRepo,
)
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _ensure_clients(session: AsyncSession) -> None:
    await AsyncClientRepo(session).ensure_default()


# ── AsyncMonitoredPackageRepo ────────────────────────────────────────────────


async def test_create_and_get_by_name_ci(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncMonitoredPackageRepo(async_db_session)
    pkg = await repo.create(
        name="Flask", ecosystem="PyPI", version="3.0.0", client_id="default", source="manual"
    )
    assert pkg.id is not None

    found = await repo.get_by_name_ci("flask", "PyPI", "default")
    assert found is not None
    assert found.id == pkg.id


async def test_list_filtered_search_and_sort(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncMonitoredPackageRepo(async_db_session)
    await repo.create(
        name="zeta-lib", ecosystem="npm", version=None, client_id="default", source="manual"
    )
    await repo.create(
        name="alpha-lib", ecosystem="npm", version=None, client_id="default", source="manual"
    )

    items, total = await repo.list_filtered("default", sort_by="name", sort_dir="asc")
    assert total == 2
    assert [i.name for i in items] == ["alpha-lib", "zeta-lib"]

    items, total = await repo.list_filtered("default", search="alpha")
    assert total == 1
    assert items[0].name == "alpha-lib"


async def test_apply_scan_summary_noop_when_package_not_monitored(
    async_db_session: AsyncSession,
) -> None:
    """Port kuirk `update_one` TANPA `upsert=True` lama -- dependensi
    transitif yang gak dimonitor, apply-nya diem2 no-op."""
    repo = AsyncMonitoredPackageRepo(async_db_session)
    applied = await repo.apply_scan_summary("never-added", "npm", "default", vuln_count=5)
    assert applied is False


async def test_delete_removes_package(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncMonitoredPackageRepo(async_db_session)
    pkg = await repo.create(
        name="doomed", ecosystem="npm", version=None, client_id="default", source="manual"
    )
    await repo.delete(pkg)
    assert await repo.get_by_id(pkg.id, "default") is None


# ── AsyncPackageVulnRepo ─────────────────────────────────────────────────────


async def test_upsert_preserves_ack_fields_on_second_scan(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncPackageVulnRepo(async_db_session)
    v1 = await repo.upsert(
        package_name="lodash",
        ecosystem="npm",
        advisory_id="GHSA-xxxx",
        client_id="default",
        pinned_version="4.17.15",
        aliases=["CVE-2020-8203"],
        summary="Prototype pollution",
        details="",
        severity="HIGH",
        cvss_score=7.4,
        adjusted_score=7.4,
        adjusted_severity="HIGH",
        published=None,
        modified=None,
        fixed_version="4.17.19",
        affected_version_ranges=[],
        references=[],
        source="osv.dev",
        last_updated=datetime.datetime.now(datetime.UTC),
    )
    await repo.toggle_acknowledge(v1, "analyst1")
    assert v1.acknowledged is True

    # Scan ulang -- upsert kedua HARUS nimpa `$set` fields (severity dkk)
    # tapi TETAP pertahankan `acknowledged`/`ack_by` ($setOnInsert lama).
    v2 = await repo.upsert(
        package_name="lodash",
        ecosystem="npm",
        advisory_id="GHSA-xxxx",
        client_id="default",
        pinned_version="4.17.15",
        aliases=["CVE-2020-8203"],
        summary="Prototype pollution (updated)",
        details="",
        severity="CRITICAL",
        cvss_score=9.1,
        adjusted_score=9.1,
        adjusted_severity="CRITICAL",
        published=None,
        modified=None,
        fixed_version="4.17.19",
        affected_version_ranges=[],
        references=[],
        source="osv.dev",
        last_updated=datetime.datetime.now(datetime.UTC),
    )
    assert v2.id == v1.id
    assert v2.severity == "CRITICAL"
    assert v2.acknowledged is True
    assert v2.ack_by == "analyst1"


async def test_list_filtered_by_severity_and_search(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncPackageVulnRepo(async_db_session)
    now = datetime.datetime.now(datetime.UTC)
    await repo.upsert(
        package_name="pkg-a",
        ecosystem="npm",
        advisory_id="GHSA-1",
        client_id="default",
        severity="CRITICAL",
        adjusted_severity="CRITICAL",
        summary="bad stuff",
        aliases=["CVE-2024-0001"],
        affected_version_ranges=[],
        references=[],
        last_updated=now,
        source="osv.dev",
    )
    await repo.upsert(
        package_name="pkg-b",
        ecosystem="npm",
        advisory_id="GHSA-2",
        client_id="default",
        severity="LOW",
        adjusted_severity="LOW",
        summary="minor thing",
        aliases=[],
        affected_version_ranges=[],
        references=[],
        last_updated=now,
        source="osv.dev",
    )

    items, total = await repo.list_filtered("default", severity="critical")
    assert total == 1
    assert items[0].package_name == "pkg-a"

    items, total = await repo.list_filtered("default", search="CVE-2024-0001")
    assert total == 1
    assert items[0].advisory_id == "GHSA-1"


async def test_delete_for_package(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncPackageVulnRepo(async_db_session)
    now = datetime.datetime.now(datetime.UTC)
    await repo.upsert(
        package_name="pkg-c",
        ecosystem="npm",
        advisory_id="GHSA-3",
        client_id="default",
        severity="HIGH",
        aliases=[],
        affected_version_ranges=[],
        references=[],
        last_updated=now,
        source="osv.dev",
    )
    await repo.delete_for_package("pkg-c", "npm", "default")
    _, total = await repo.list_filtered("default", package_name="pkg-c")
    assert total == 0


async def test_get_severity_stats(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncPackageVulnRepo(async_db_session)
    now = datetime.datetime.now(datetime.UTC)
    await repo.upsert(
        package_name="pkg-d",
        ecosystem="npm",
        advisory_id="GHSA-4",
        client_id="default",
        severity="CRITICAL",
        aliases=[],
        affected_version_ranges=[],
        references=[],
        last_updated=now,
        source="osv.dev",
    )
    stats = await repo.get_severity_stats("default")
    assert stats["critical"] == 1
    assert stats["total_vulns"] == 1
    assert stats["unacknowledged"] == 1
    assert stats["kev_count"] == 0


# ── AsyncPackageDepGraphRepo ─────────────────────────────────────────────────


async def test_dep_graph_upsert(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    pkg = await AsyncMonitoredPackageRepo(async_db_session).create(
        name="graph-pkg", ecosystem="npm", version="1.0.0", client_id="default", source="manual"
    )
    dep_repo = AsyncPackageDepGraphRepo(async_db_session)
    doc = await dep_repo.upsert(
        pkg.id,
        package_name="graph-pkg",
        ecosystem="npm",
        version="1.0.0",
        resolved_at=datetime.datetime.now(datetime.UTC),
        direct_count=2,
        indirect_count=5,
        total_count=7,
        direct_deps=[{"name": "dep-a", "version": "1.0.0", "system": "NPM"}],
        indirect_deps=[],
        scorecard_score=8.5,
        scorecard_date="2024-01-01",
        scorecard_project="github.com/example/graph-pkg",
        scorecard_checks=[],
        error=None,
    )
    assert doc.pkg_id == pkg.id

    updated = await dep_repo.upsert(pkg.id, total_count=8, direct_count=2, indirect_count=6)
    assert updated.id == doc.id
    assert updated.total_count == 8


# ── Service-level: add/update/delete/import (httpx eksternal di-mock) ──────


async def test_add_package_success(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    with patch.object(
        pkg_vuln_service, "_package_exists_on_registry", AsyncMock(return_value=True)
    ):
        result = await pkg_vuln_service.add_package(
            async_db_session, "requests", "PyPI", version="2.31.0", client_id="default"
        )
    assert result["success"] is True
    pkg = await AsyncMonitoredPackageRepo(async_db_session).get_by_id(result["id"], "default")
    assert pkg is not None
    assert pkg.name == "requests"


async def test_add_package_invalid_ecosystem() -> None:
    result = await pkg_vuln_service.add_package(None, "x", "not-a-real-ecosystem")  # type: ignore[arg-type]
    assert result["success"] is False
    assert "invalid ecosystem" in result["reason"]


async def test_add_package_not_found_on_registry(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    with patch.object(
        pkg_vuln_service, "_package_exists_on_registry", AsyncMock(return_value=False)
    ):
        result = await pkg_vuln_service.add_package(
            async_db_session, "totally-fake-pkg-xyz", "PyPI"
        )
    assert result["success"] is False
    assert "not found on" in result["reason"]


async def test_add_package_duplicate(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    with patch.object(
        pkg_vuln_service, "_package_exists_on_registry", AsyncMock(return_value=True)
    ):
        await pkg_vuln_service.add_package(async_db_session, "flask", "PyPI", client_id="default")
        result = await pkg_vuln_service.add_package(
            async_db_session, "Flask", "PyPI", client_id="default"
        )
    assert result["success"] is False
    assert result["reason"] == "duplicate"


async def test_update_package_rescan_flag_and_vuln_cleanup(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    pkg_repo = AsyncMonitoredPackageRepo(async_db_session)
    pkg = await pkg_repo.create(
        name="httpx", ecosystem="PyPI", version="0.27.0", client_id="default", source="manual"
    )
    vuln_repo = AsyncPackageVulnRepo(async_db_session)
    await vuln_repo.upsert(
        package_name="httpx",
        ecosystem="PyPI",
        advisory_id="GHSA-old",
        client_id="default",
        severity="LOW",
        aliases=[],
        affected_version_ranges=[],
        references=[],
        last_updated=datetime.datetime.now(datetime.UTC),
        source="osv.dev",
    )

    result = await pkg_vuln_service.update_package(
        async_db_session, pkg.id, version="0.28.0", client_id="default"
    )
    assert result["success"] is True
    assert result["rescan"] is True

    # Vuln lama buat versi sebelumnya harus kehapus (nunggu rescan baru).
    _, total = await vuln_repo.list_filtered("default", package_name="httpx")
    assert total == 0


async def test_update_package_no_changes(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    pkg = await AsyncMonitoredPackageRepo(async_db_session).create(
        name="same-version", ecosystem="npm", version="1.0.0", client_id="default", source="manual"
    )
    result = await pkg_vuln_service.update_package(
        async_db_session, pkg.id, version="1.0.0", client_id="default"
    )
    assert result == {"success": True, "changed": False}


async def test_delete_package_cleans_up_vulns(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    pkg = await AsyncMonitoredPackageRepo(async_db_session).create(
        name="to-delete", ecosystem="npm", version=None, client_id="default", source="manual"
    )
    vuln_repo = AsyncPackageVulnRepo(async_db_session)
    await vuln_repo.upsert(
        package_name="to-delete",
        ecosystem="npm",
        advisory_id="GHSA-x",
        client_id="default",
        severity="LOW",
        aliases=[],
        affected_version_ranges=[],
        references=[],
        last_updated=datetime.datetime.now(datetime.UTC),
        source="osv.dev",
    )

    result = await pkg_vuln_service.delete_package(async_db_session, pkg.id, client_id="default")
    assert result["success"] is True
    _, total = await vuln_repo.list_filtered("default", package_name="to-delete")
    assert total == 0


async def test_import_lockfile_adds_and_skips_duplicates(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    content = "flask==3.0.0\nrequests==2.31.0\n"
    result = await pkg_vuln_service.import_lockfile(
        async_db_session, "requirements.txt", content, client_id="default"
    )
    assert result["parsed"] == 2
    assert result["added"] == 2
    assert result["skipped"] == 0

    # Import lagi -- sekarang harus semua ke-skip (udah ada).
    result2 = await pkg_vuln_service.import_lockfile(
        async_db_session, "requirements.txt", content, client_id="default"
    )
    assert result2["added"] == 0
    assert result2["skipped"] == 2


# ── Task 10: dry run, ecosystem override, source path, stats ─────────────────


async def _pkg_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(MonitoredPackage))).scalar_one()


async def test_dry_run_writes_nothing(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    repo = AsyncMonitoredPackageRepo(api_session)
    await repo.create(
        name="flask", ecosystem="PyPI", version="3.0.0", client_id="default", source="manual"
    )
    await repo.create(
        name="requests", ecosystem="PyPI", version="2.30.0", client_id="default", source="manual"
    )
    before = await _pkg_count(api_session)
    audit_before = (
        await api_session.execute(select(func.count()).select_from(AuditLogEntry))
    ).scalar_one()
    resp = await api_client.post(
        "/api/pkgvuln/import-lockfile",
        headers=auth_header(),
        data={"dry_run": "true"},
        files={"file": ("requirements.txt", b"flask==3.0.0\nrequests==2.31.0\ndjango==5.0.0\n")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["new"] == 1
    assert body["already_monitored"] == 1
    assert body["version_changes"] == 1
    assert body["detected_format"] == "requirements"
    assert await _pkg_count(api_session) == before
    audit_after = (
        await api_session.execute(select(func.count()).select_from(AuditLogEntry))
    ).scalar_one()
    assert audit_after == audit_before
    req = await repo.get_by_name_ci("requests", "PyPI", "default")
    assert req is not None and req.version == "2.30.0"


async def test_import_sets_source_path(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await pkg_vuln_service.import_lockfile(
        async_db_session, "requirements.txt", "flask==3.0.0\n", "default", project="shop-api"
    )
    pkg = await AsyncMonitoredPackageRepo(async_db_session).get_by_name_ci(
        "flask", "PyPI", "default"
    )
    assert pkg is not None
    assert pkg.source_path == "shop-api/requirements.txt"
    await pkg_vuln_service.import_lockfile(
        async_db_session, "requirements.txt", "flask==3.0.0\n", "default", project="other"
    )
    await async_db_session.refresh(pkg)
    assert pkg.source_path == "shop-api/requirements.txt"


async def test_import_truncates_long_source_path(async_db_session: AsyncSession) -> None:
    """`source_path` String(500): nama file yang kepanjangan dipotong, impor tidak gagal."""
    await _ensure_clients(async_db_session)
    long_name = "d" * 600 + "/requirements.txt"
    await pkg_vuln_service.import_lockfile(
        async_db_session, long_name, "flask==3.0.0\n", "default", ecosystem="PyPI"
    )
    pkg = await AsyncMonitoredPackageRepo(async_db_session).get_by_name_ci(
        "flask", "PyPI", "default"
    )
    assert pkg is not None
    assert pkg.source_path == long_name[:500]


async def test_unknown_lockfile_auto_is_422(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    resp = await api_client.post(
        "/api/pkgvuln/import-lockfile",
        headers=auth_header(),
        files={"file": ("deps.txt", b"flask==3.0.0\n")},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Unrecognised lockfile, choose the ecosystem"


async def test_project_with_dotdot_is_422(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    resp = await api_client.post(
        "/api/pkgvuln/import-lockfile",
        headers=auth_header(),
        data={"project": "../etc"},
        files={"file": ("requirements.txt", b"flask==3.0.0\n")},
    )
    assert resp.status_code == 422


async def test_stats_vulnerable_packages(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    repo = AsyncMonitoredPackageRepo(api_session)
    await repo.create(name="a", ecosystem="PyPI", version="1", client_id="default", source="manual")
    b = await repo.create(
        name="b", ecosystem="PyPI", version="1", client_id="default", source="manual"
    )
    b.vuln_count = 3
    await api_session.flush()
    resp = await api_client.get("/api/pkgvuln/stats", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json()["vulnerable_packages"] == 1
    assert resp.json()["packages"] == 2


async def test_packages_ecosystem_filter(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    repo = AsyncMonitoredPackageRepo(api_session)
    await repo.create(
        name="flask", ecosystem="PyPI", version="1", client_id="default", source="manual"
    )
    await repo.create(
        name="lodash", ecosystem="npm", version="1", client_id="default", source="manual"
    )
    resp = await api_client.get(
        "/api/pkgvuln/packages", headers=auth_header(), params={"ecosystem": "npm"}
    )
    assert resp.status_code == 200
    assert [i["name"] for i in resp.json()["items"]] == ["lodash"]
    resp = await api_client.get("/api/pkgvuln/packages", headers=auth_header())
    assert resp.json()["total"] == 2
