"""Integration test `AsyncTechStackRepo` -- Postgres REAL (testcontainers).
Fase 7.3 (router `techstack`)."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

import pytest
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.techstack import AsyncTechStackRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _ensure_clients(session: AsyncSession) -> None:
    repo = AsyncClientRepo(session)
    await repo.ensure_default()
    if await repo.get("acme") is None:
        await repo.create(client_id="acme", name="Acme", countries=[])


async def test_create_and_list(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTechStackRepo(async_db_session)

    entry, reason = await repo.create(name="Apache Struts", client_id="default")
    assert reason == "ok"
    assert entry is not None
    assert entry.source == "manual"
    assert entry.added_date is not None

    items, total = await repo.list_filtered(client_id="default")
    assert total == 1
    assert items[0].name == "Apache Struts"


async def test_create_is_case_insensitive_duplicate(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTechStackRepo(async_db_session)

    await repo.create(name="Apache Struts", client_id="default")
    entry, reason = await repo.create(name="apache struts", client_id="default")
    assert entry is None
    assert reason == "duplicate"

    _, total = await repo.list_filtered(client_id="default")
    assert total == 1


async def test_create_same_name_different_clients_both_allowed(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTechStackRepo(async_db_session)

    entry1, r1 = await repo.create(name="nginx", client_id="default")
    entry2, r2 = await repo.create(name="nginx", client_id="acme")
    assert r1 == r2 == "ok"
    assert entry1 is not None
    assert entry2 is not None
    assert entry1.id != entry2.id

    _, total_default = await repo.list_filtered(client_id="default")
    _, total_acme = await repo.list_filtered(client_id="acme")
    assert total_default == 1
    assert total_acme == 1


async def test_create_invalid_exposure_hosting_falls_back_to_default(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTechStackRepo(async_db_session)

    entry, _ = await repo.create(
        name="nginx", client_id="default", exposure="not-real", hosting_type="not-real"
    )
    assert entry is not None
    assert entry.exposure == "internal"
    assert entry.hosting_type == "on_prem"


async def test_list_filtered_by_search(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTechStackRepo(async_db_session)
    await repo.create(name="Apache Struts", client_id="default")
    await repo.create(name="nginx", client_id="default")

    _, total = await repo.list_filtered(client_id="default", search="apache")
    assert total == 1


async def test_list_filtered_scoped_per_client(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTechStackRepo(async_db_session)
    await repo.create(name="nginx", client_id="default")
    await repo.create(name="Apache Struts", client_id="acme")

    _, total_default = await repo.list_filtered(client_id="default")
    _, total_acme = await repo.list_filtered(client_id="acme")
    assert total_default == 1
    assert total_acme == 1


async def test_update_exposure_valid_and_invalid(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTechStackRepo(async_db_session)
    entry, _ = await repo.create(name="nginx", client_id="default")
    assert entry is not None

    assert await repo.update_exposure(entry.id, "public", "default") is True
    fetched = await repo.get_by_id(entry.id, "default")
    assert fetched is not None
    assert fetched.exposure == "public"

    assert await repo.update_exposure(entry.id, "not-valid", "default") is False


async def test_update_exposure_scoped_to_client(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTechStackRepo(async_db_session)
    entry, _ = await repo.create(name="nginx", client_id="default")
    assert entry is not None

    # tech milik "default", diakses lewat client "acme" -- harus gagal
    assert await repo.update_exposure(entry.id, "public", "acme") is False


async def test_update_hosting_valid_and_invalid(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTechStackRepo(async_db_session)
    entry, _ = await repo.create(name="nginx", client_id="default")
    assert entry is not None

    assert await repo.update_hosting(entry.id, "saas", "default") is True
    assert await repo.update_hosting(entry.id, "bogus", "default") is False


async def test_delete_removes_entry(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTechStackRepo(async_db_session)
    entry, _ = await repo.create(name="nginx", client_id="default")
    assert entry is not None

    assert await repo.delete(entry.id, "default") is True
    assert await repo.get_by_id(entry.id, "default") is None
    assert await repo.delete(entry.id, "default") is False


async def test_get_risk_context(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTechStackRepo(async_db_session)
    await repo.create(name="nginx", client_id="default", exposure="public", hosting_type="cloud")
    await repo.create(name="Apache Struts", client_id="default")

    ctx = await repo.get_risk_context("default")
    assert ctx["nginx"] == {"exposure": "public", "hosting_type": "cloud"}
    assert ctx["apache struts"] == {"exposure": "internal", "hosting_type": "on_prem"}


async def test_active_names_all_clients_is_the_distinct_union_of_active_entries(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTechStackRepo(async_db_session)
    assert await repo.active_names_all_clients() == []

    default_fortinet, _ = await repo.create(name="Fortinet", client_id="default")
    await repo.create(name="Nginx", client_id="default")
    await repo.create(name="Fortinet", client_id="acme")  # nama sama di client lain: sekali
    hidden, _ = await repo.create(name="Zabbix", client_id="acme")
    assert default_fortinet is not None and hidden is not None
    await repo.set_active(hidden.id, "acme", False)  # nonaktif = disembunyikan, bukan dipantau

    assert await repo.active_names_all_clients() == ["Fortinet", "Nginx"]


# ── match_count dan coverage (2a, item 6/7) ──────────────────────────────────────────────────


async def _tracker(session: AsyncSession, cve_id: str, tech: str, client_id: str) -> None:
    from cti_core.db.models.cve import CveTracker

    session.add(CveTracker(cve_id=cve_id, client_id=client_id, tech=tech))
    await session.flush()


async def test_count_by_tech_excludes_fps_and_other_clients(
    async_db_session: AsyncSession,
) -> None:
    from cti_core.db.models.cve import CveFalsePositive
    from cti_core.db.repositories.cve import AsyncCveTrackerRepo

    await _ensure_clients(async_db_session)
    await _tracker(async_db_session, "CVE-2026-0001", "nginx", "default")
    await _tracker(async_db_session, "CVE-2026-0002", "nginx", "default")
    await _tracker(async_db_session, "CVE-2026-0003", "nginx", "default")  # akan ditandai FP
    await _tracker(async_db_session, "CVE-2026-0004", "nginx", "acme")
    async_db_session.add(CveFalsePositive(cve_id="CVE-2026-0003", client_id="default"))
    await async_db_session.flush()

    counts = await AsyncCveTrackerRepo(async_db_session).count_by_tech("default")
    assert counts == {"nginx": 2}


async def test_count_by_tech_case_insensitive_and_hidden_entry_counted(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _ensure_clients(api_session)
    repo = AsyncTechStackRepo(api_session)
    entry, _ = await repo.create(name="NGINX", client_id="default")
    assert entry is not None
    await repo.set_active(entry.id, "default", False)
    await _tracker(api_session, "CVE-2026-0001", "nginx", "default")
    await _tracker(api_session, "CVE-2026-0002", "Nginx", "default")

    items = (await api_client.get("/api/techstack", headers=auth_header())).json()["items"]
    assert [(i["name"], i["match_count"], i["active"]) for i in items] == [("NGINX", 2, False)]


async def test_coverage_buckets(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    from cti_core.catalog_resolve import AffectedEntry, resolve_all
    from cti_core.db.models.catalog import CatalogFamily, CatalogVendor
    from cti_core.db.repositories.catalog import CveMirrorRepo, MirrorRecord
    from sqlalchemy import select

    await _ensure_clients(api_session)
    d = datetime.date(2026, 3, 1)

    def _seed(sync: Any) -> None:
        CveMirrorRepo(sync).upsert(
            MirrorRecord(
                cve_id="CVE-2026-0001",
                published_date=d,
                published_at=datetime.datetime.combine(d, datetime.time(9), tzinfo=datetime.UTC),
                modified_at=datetime.datetime.combine(d, datetime.time(9), tzinfo=datetime.UTC),
                summary="x",
                link="https://example.org",
            ),
            resolve_all([AffectedEntry(vendor="Fortinet", product="FortiOS")]),
        )

    await api_session.run_sync(_seed)
    await api_session.flush()
    vendor_id = (
        await api_session.execute(select(CatalogVendor.id).where(CatalogVendor.key == "fortinet"))
    ).scalar_one()
    family_id = (
        await api_session.execute(select(CatalogFamily.id).where(CatalogFamily.key == "fortios"))
    ).scalar_one()

    repo = AsyncTechStackRepo(api_session)
    v, _ = await repo.create_from_target(client_id="default", vendor_id=vendor_id)
    f, _ = await repo.create_from_target(client_id="default", family_id=family_id)
    u, _ = await repo.create(name="custom", client_id="default")
    h, _ = await repo.create_from_target(
        client_id="default", family_id=family_id, name="FortiOS hidden"
    )
    assert v and f and u and h
    await repo.set_active(h.id, "default", False)
    other, _ = await repo.create(name="acme-only", client_id="acme")  # client lain: tidak dihitung
    assert other is not None

    body = (await api_client.get("/api/techstack/coverage", headers=auth_header())).json()
    assert body == {
        "total": 4,
        "active": 3,
        "mapped_vendor": 1,
        "mapped_family": 1,
        "unmapped": 1,
        "hidden": 1,
    }
