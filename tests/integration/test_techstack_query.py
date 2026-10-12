"""Integration test `AsyncTechStackRepo` -- Postgres REAL (testcontainers).
Fase 7.3 (router `techstack`)."""

from __future__ import annotations

import pytest
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.techstack import AsyncTechStackRepo
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
