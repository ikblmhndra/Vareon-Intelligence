"""Integration test `AsyncSourceReliabilityRepo` -- Postgres REAL
(testcontainers). Fase 7.3 (router `source_reliability`, Bagian 2)."""

from __future__ import annotations

import pytest
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.source_reliability import AsyncSourceReliabilityRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_add_entry_and_list(async_db_session: AsyncSession) -> None:
    repo = AsyncSourceReliabilityRepo(async_db_session)
    entry, reason = await repo.add_entry(
        source_name="BleepingComputer",
        analyst_name="analyst1",
        reliability_grade="b",
        credibility_code="2",
        notes="consistently accurate",
    )
    assert entry is not None
    assert reason == "ok"
    assert entry.reliability_grade == "B"
    assert entry.admiralty_code == "B2"

    entries, total = await repo.list_entries()
    assert total == 1
    assert entries[0].source_name == "BleepingComputer"


async def test_add_entry_duplicate_case_insensitive(async_db_session: AsyncSession) -> None:
    repo = AsyncSourceReliabilityRepo(async_db_session)
    await repo.add_entry(
        source_name="BleepingComputer",
        analyst_name="a1",
        reliability_grade="B",
        credibility_code="2",
        notes="",
    )
    entry, reason = await repo.add_entry(
        source_name="bleepingcomputer",
        analyst_name="a2",
        reliability_grade="A",
        credibility_code="1",
        notes="",
    )
    assert entry is None
    assert reason == "duplicate"


async def test_list_entries_filters_by_search_and_grade(async_db_session: AsyncSession) -> None:
    repo = AsyncSourceReliabilityRepo(async_db_session)
    await repo.add_entry(
        source_name="BleepingComputer",
        analyst_name="a1",
        reliability_grade="B",
        credibility_code="2",
        notes="",
    )
    await repo.add_entry(
        source_name="Krebs on Security",
        analyst_name="a1",
        reliability_grade="A",
        credibility_code="1",
        notes="",
    )

    by_search, total1 = await repo.list_entries(search="krebs")
    assert total1 == 1
    assert by_search[0].source_name == "Krebs on Security"

    by_grade, total2 = await repo.list_entries(grade="a")
    assert total2 == 1
    assert by_grade[0].reliability_grade == "A"


async def test_update_entry(async_db_session: AsyncSession) -> None:
    repo = AsyncSourceReliabilityRepo(async_db_session)
    entry, _ = await repo.add_entry(
        source_name="BleepingComputer",
        analyst_name="a1",
        reliability_grade="B",
        credibility_code="2",
        notes="",
    )
    assert entry is not None

    ok = await repo.update_entry(
        entry.id, analyst_name="a2", reliability_grade="a", credibility_code="1", notes="upgraded"
    )
    assert ok is True

    refreshed = await repo.get_by_id(entry.id)
    assert refreshed is not None
    assert refreshed.reliability_grade == "A"
    assert refreshed.admiralty_code == "A1"
    assert refreshed.notes == "upgraded"


async def test_update_entry_missing_returns_false(async_db_session: AsyncSession) -> None:
    repo = AsyncSourceReliabilityRepo(async_db_session)
    ok = await repo.update_entry(
        999999, analyst_name="a", reliability_grade="A", credibility_code="1", notes=""
    )
    assert ok is False


async def test_delete_entry(async_db_session: AsyncSession) -> None:
    repo = AsyncSourceReliabilityRepo(async_db_session)
    entry, _ = await repo.add_entry(
        source_name="BleepingComputer",
        analyst_name="a1",
        reliability_grade="B",
        credibility_code="2",
        notes="",
    )
    assert entry is not None

    assert await repo.delete_entry(entry.id) is True
    assert await repo.get_by_id(entry.id) is None
    assert await repo.delete_entry(entry.id) is False


async def test_get_stats_groups_by_grade(async_db_session: AsyncSession) -> None:
    repo = AsyncSourceReliabilityRepo(async_db_session)
    await repo.add_entry(
        source_name="Src A", analyst_name="a", reliability_grade="A", credibility_code="1", notes=""
    )
    await repo.add_entry(
        source_name="Src B", analyst_name="a", reliability_grade="A", credibility_code="1", notes=""
    )
    await repo.add_entry(
        source_name="Src C", analyst_name="a", reliability_grade="B", credibility_code="2", notes=""
    )

    stats = await repo.get_stats()
    assert stats["total"] == 3
    by_grade = {row["grade"]: row["count"] for row in stats["by_grade"]}
    assert by_grade == {"A": 2, "B": 1}


async def test_get_ungraded_sources(async_db_session: AsyncSession) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    await article_repo.upsert(url="https://example.com/1", title="t1", source="gbhacker")
    await article_repo.upsert(url="https://example.com/2", title="t2", source="BleepingComputer")

    sr_repo = AsyncSourceReliabilityRepo(async_db_session)
    await sr_repo.add_entry(
        source_name="bleepingcomputer",
        analyst_name="a",
        reliability_grade="B",
        credibility_code="2",
        notes="",
    )

    ungraded = await sr_repo.get_ungraded_sources()
    assert ungraded == ["gbhacker"]


async def test_origin_filter(async_db_session: AsyncSession) -> None:
    repo = AsyncSourceReliabilityRepo(async_db_session)
    await repo.add_entry(
        source_name="Manual Src",
        analyst_name="a1",
        reliability_grade="B",
        credibility_code="2",
        notes="",
    )
    await repo.ensure_defaults({"Auto Src": "news"})

    analyst, total_a = await repo.list_entries(origin="analyst")
    assert total_a == 1
    assert [e.source_name for e in analyst] == ["Manual Src"]
    default, total_d = await repo.list_entries(origin="default")
    assert [e.source_name for e in default] == ["Auto Src"]
    assert total_d == 1


async def test_id_tiebreaker_stable_pages(async_db_session: AsyncSession) -> None:
    """Lima baris dengan `last_updated` sama: tanpa tie-breaker `id`, halaman offset bisa
    menduplikasi atau melewatkan baris."""
    repo = AsyncSourceReliabilityRepo(async_db_session)
    for i in range(5):
        await repo.add_entry(
            source_name=f"Src {i}",
            analyst_name="a1",
            reliability_grade="B",
            credibility_code="2",
            notes="",
        )
    seen: list[int] = []
    for page in (1, 2, 3):
        rows, total = await repo.list_entries(
            page=page, page_size=2, sort_by="last_updated", sort_dir="desc"
        )
        assert total == 5
        seen.extend(e.id for e in rows)
    assert len(seen) == 5
    assert len(set(seen)) == 5
