"""Integration test `AsyncIOCRepo` (query/tag/TA/delete methods baru) +
`AsyncIocAllowlistRepo` -- Postgres REAL (testcontainers). Fase 7.3
(router `iocs`)."""

from __future__ import annotations

from typing import cast

import pytest
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from cti_core.db.repositories.ioc_reference import AsyncIocAllowlistRepo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _seed(repo: AsyncIndicatorRepo) -> dict[str, int]:
    ip = await repo.upsert(
        type="ip", value="45.33.32.156", source_url="https://a.com", source_name="a"
    )
    domain = await repo.upsert(
        type="domain", value="evil.example", source_url="https://b.com", source_name="b"
    )
    url = await repo.upsert(
        type="url", value="http://bad.example/x", source_url="https://c.com", source_name="c"
    )
    return {"ip": ip.id, "domain": domain.id, "url": url.id}


async def test_list_filtered_by_type(async_db_session: AsyncSession) -> None:
    repo = AsyncIndicatorRepo(async_db_session)
    ids = await _seed(repo)

    iocs, total = await repo.list_filtered(ioc_type="ip")
    assert total == 1
    assert iocs[0].id == ids["ip"]


async def test_list_filtered_by_search(async_db_session: AsyncSession) -> None:
    repo = AsyncIndicatorRepo(async_db_session)
    ids = await _seed(repo)

    iocs, total = await repo.list_filtered(search="evil")
    assert total == 1
    assert iocs[0].id == ids["domain"]


async def test_list_filtered_ignores_unknown_type(async_db_session: AsyncSession) -> None:
    repo = AsyncIndicatorRepo(async_db_session)
    await _seed(repo)

    # port dari `ioc_service.get_iocs()`: tipe gak dikenal diabaikan (bukan
    # 422), balik semua data kayak gak ada filter.
    _, total = await repo.list_filtered(ioc_type="not-a-real-type")
    assert total == 3


async def test_list_filtered_pagination(async_db_session: AsyncSession) -> None:
    repo = AsyncIndicatorRepo(async_db_session)
    await _seed(repo)

    page1, total = await repo.list_filtered(page=1, page_size=2)
    page2, _ = await repo.list_filtered(page=2, page_size=2)
    assert total == 3
    assert len(page1) == 2
    assert len(page2) == 1


async def test_get_stats_groups_by_type(async_db_session: AsyncSession) -> None:
    repo = AsyncIndicatorRepo(async_db_session)
    await _seed(repo)
    await repo.upsert(type="ip", value="1.1.1.1", source_url="https://d.com", source_name="d")

    stats = await repo.get_stats()
    assert stats["total"] == 4
    rows = cast("list[dict[str, object]]", stats["by_type"])
    by_type = {row["type"]: row["count"] for row in rows}
    assert by_type["ip"] == 2
    assert by_type["domain"] == 1
    assert by_type["url"] == 1


async def test_add_tags_is_idempotent(async_db_session: AsyncSession) -> None:
    repo = AsyncIndicatorRepo(async_db_session)
    ids = await _seed(repo)
    ioc = await repo.get_by_id(ids["ip"])
    assert ioc is not None

    await repo.add_tags(ioc, ["c2", "botnet"])
    await repo.add_tags(ioc, ["c2", "new-tag"])  # "c2" diulang -- gak boleh dobel

    fetched = await repo.get_by_id(ids["ip"])
    assert fetched is not None
    assert sorted(t.tag for t in fetched.tags) == ["botnet", "c2", "new-tag"]


async def test_add_threat_actors_is_idempotent(async_db_session: AsyncSession) -> None:
    repo = AsyncIndicatorRepo(async_db_session)
    ids = await _seed(repo)
    ioc = await repo.get_by_id(ids["ip"])
    assert ioc is not None

    await repo.add_threat_actors(ioc, ["Apt41", "Turla"])
    await repo.add_threat_actors(ioc, ["Apt41"])

    fetched = await repo.get_by_id(ids["ip"])
    assert fetched is not None
    assert sorted(t.threat_actor for t in fetched.threat_actors) == ["Apt41", "Turla"]


async def test_remove_threat_actor_updates_in_memory_collection_immediately(
    async_db_session: AsyncSession,
) -> None:
    """Regression: `session.delete()` langsung pada child gak nyabut dia
    dari koleksi in-memory parent (bug yang sama kejadian di
    `AsyncUserRepo.update_client_ids`, Fase 7.2) -- `remove_threat_actor`
    pakai `.remove()` dari koleksi, bukan `session.delete()` langsung,
    biar `ioc.threat_actors` di objek YANG SAMA langsung ke-update tanpa
    perlu fetch ulang."""
    repo = AsyncIndicatorRepo(async_db_session)
    ids = await _seed(repo)
    ioc = await repo.get_by_id(ids["ip"])
    assert ioc is not None
    await repo.add_threat_actors(ioc, ["Apt41", "Turla"])

    ok = await repo.remove_threat_actor(ioc, "Apt41")
    assert ok is True
    # cek di objek YANG SAMA, TANPA fetch ulang -- ini yang gagal kalau
    # bug staleness balik lagi.
    assert [t.threat_actor for t in ioc.threat_actors] == ["Turla"]

    fetched = await repo.get_by_id(ids["ip"])
    assert fetched is not None
    assert [t.threat_actor for t in fetched.threat_actors] == ["Turla"]


async def test_remove_threat_actor_returns_false_when_not_tagged(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncIndicatorRepo(async_db_session)
    ids = await _seed(repo)
    ioc = await repo.get_by_id(ids["ip"])
    assert ioc is not None

    assert await repo.remove_threat_actor(ioc, "Ghost") is False


async def test_delete_removes_ioc(async_db_session: AsyncSession) -> None:
    repo = AsyncIndicatorRepo(async_db_session)
    ids = await _seed(repo)

    assert await repo.delete(ids["ip"]) is True
    assert await repo.get_by_id(ids["ip"]) is None
    assert await repo.delete(ids["ip"]) is False


async def test_bulk_delete_returns_count_of_actually_deleted(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncIndicatorRepo(async_db_session)
    ids = await _seed(repo)

    count = await repo.bulk_delete([ids["ip"], ids["domain"], 999999])
    assert count == 2
    _, total = await repo.list_filtered()
    assert total == 1


class TestAsyncIocAllowlistRepo:
    @pytest.fixture(autouse=True)
    async def _without_seed(self, async_db_session: AsyncSession) -> None:
        # Skema test sudah di head: seed migrasi 0.8.6 ada di tabel; test ini menghitung baris.
        await async_db_session.execute(text("DELETE FROM ioc_allowlist_entries"))

    async def test_create_and_list(self, async_db_session: AsyncSession) -> None:
        repo = AsyncIocAllowlistRepo(async_db_session)
        entry = await repo.create(entry_type="ip", value="1.2.3.4", added_by="admin1")
        assert entry.added_by == "admin1"
        assert entry.value == "1.2.3.4"

        entries = await repo.list_all()
        assert len(entries) == 1

    async def test_create_is_idempotent_by_type_and_value(
        self, async_db_session: AsyncSession
    ) -> None:
        repo = AsyncIocAllowlistRepo(async_db_session)
        first = await repo.create(entry_type="ip", value="1.2.3.4", added_by="admin1")
        second = await repo.create(entry_type="ip", value="1.2.3.4", added_by="admin2")
        assert first.id == second.id
        assert (await repo.list_all()) and len(await repo.list_all()) == 1

    async def test_create_normalizes_value_case_and_whitespace(
        self, async_db_session: AsyncSession
    ) -> None:
        repo = AsyncIocAllowlistRepo(async_db_session)
        entry = await repo.create(
            entry_type="email_domain", value="  Example.COM  ", added_by="admin1"
        )
        assert entry.value == "example.com"

    async def test_create_rejects_unknown_type(self, async_db_session: AsyncSession) -> None:
        repo = AsyncIocAllowlistRepo(async_db_session)
        with pytest.raises(ValueError, match="type harus"):
            await repo.create(entry_type="not-a-type", value="x", added_by="admin1")

    async def test_delete_returns_false_when_missing(self, async_db_session: AsyncSession) -> None:
        repo = AsyncIocAllowlistRepo(async_db_session)
        assert await repo.delete(999999) is False

    async def test_delete_removes_entry(self, async_db_session: AsyncSession) -> None:
        repo = AsyncIocAllowlistRepo(async_db_session)
        entry = await repo.create(entry_type="ip", value="1.2.3.4", added_by="admin1")
        assert await repo.delete(entry.id) is True
        assert await repo.list_all() == []
