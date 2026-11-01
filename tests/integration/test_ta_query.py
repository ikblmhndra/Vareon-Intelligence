"""Integration test `AsyncTARepo`/`AsyncTAProfileRepo` -- Postgres REAL
(testcontainers). Fase 7.3 (router `ta_groups`, Bagian 3)."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.ta import AsyncTAProfileRepo, AsyncTARepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _ensure_clients(session: AsyncSession) -> None:
    repo = AsyncClientRepo(session)
    await repo.ensure_default()
    if await repo.get("acme") is None:
        await repo.create(client_id="acme", name="Acme", countries=[])


async def test_add_group_and_list(async_db_session: AsyncSession) -> None:
    repo = AsyncTARepo(async_db_session)
    result = await repo.add_group("APT41")
    assert result["success"] is True

    groups, total = await repo.list_groups()
    assert total == 1
    assert groups[0].name == "APT41"
    assert groups[0].source == "manual"


async def test_add_group_duplicate_case_insensitive(async_db_session: AsyncSession) -> None:
    repo = AsyncTARepo(async_db_session)
    await repo.add_group("APT41")
    result = await repo.add_group("apt41")
    assert result == {"success": False, "reason": "duplicate"}


async def test_add_group_whitelisted_rejected(async_db_session: AsyncSession) -> None:
    repo = AsyncTARepo(async_db_session)
    result1 = await repo.add_group("BadActor")
    assert result1["success"] is True
    groups, _ = await repo.list_groups()
    group_id = groups[0].id

    await repo.delete_group(group_id, "BadActor")
    result2 = await repo.add_group("badactor")
    assert result2 == {"success": False, "reason": "whitelisted"}


async def test_delete_group_adds_to_whitelist(async_db_session: AsyncSession) -> None:
    repo = AsyncTARepo(async_db_session)
    await repo.add_group("TempGroup")
    groups, _ = await repo.list_groups()
    group_id = groups[0].id

    result = await repo.delete_group(group_id, "TempGroup")
    assert result == {"success": True}

    _groups_after, total_after = await repo.list_groups()
    assert total_after == 0

    wl_items, wl_total = await repo.list_whitelist()
    assert wl_total == 1
    assert wl_items[0].name == "tempgroup"


async def test_remove_from_whitelist(async_db_session: AsyncSession) -> None:
    repo = AsyncTARepo(async_db_session)
    await repo.add_group("TempGroup")
    groups, _ = await repo.list_groups()
    await repo.delete_group(groups[0].id, "TempGroup")

    assert await repo.remove_from_whitelist("tempgroup") is True
    assert await repo.remove_from_whitelist("tempgroup") is False


async def test_get_ta_stats(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    article_repo = AsyncArticleRepo(async_db_session)
    ta_repo = AsyncTARepo(async_db_session)

    await ta_repo.add_group("Apt41")
    await ta_repo.add_group("UnseenGroup")

    a1 = await article_repo.upsert(url="https://example.com/1", title="t1", source="s")
    await article_repo.set_enrichment(a1, threat_actors=["Apt41"])
    a2 = await article_repo.upsert(url="https://example.com/2", title="t2", source="s")
    await article_repo.set_enrichment(a2, threat_actors=["Apt41"])

    stats = await ta_repo.get_ta_stats()
    assert stats["total_groups"] == 2
    assert stats["manual_count"] == 2
    assert stats["in_news_count"] == 1
    assert stats["top_in_news"][0]["name"] == "Apt41"
    assert stats["top_in_news"][0]["count"] == 2


async def test_watchlist_scoped_by_client(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncTARepo(async_db_session)

    r1 = await repo.add_to_watchlist("Apt41", "default")
    assert r1["success"] is True
    r2 = await repo.add_to_watchlist("apt41", "default")
    assert r2 == {"success": False, "reason": "already_watched"}
    await repo.add_to_watchlist("OtherGroup", "acme")

    names_default = await repo.get_watchlist_names("default")
    names_acme = await repo.get_watchlist_names("acme")
    assert names_default == ["Apt41"]
    assert names_acme == ["OtherGroup"]

    ok = await repo.remove_from_watchlist("apt41", "default")
    assert ok is True
    assert await repo.get_watchlist_names("default") == []


async def test_get_watchlist_names_unscoped_ignores_client(async_db_session: AsyncSession) -> None:
    """Fase 7.4 Grup D -- port `get_ioc_ta_links()`'s watchlist check
    LINTAS SEMUA client (asimetri legacy dipertahankan apa adanya)."""
    await _ensure_clients(async_db_session)
    repo = AsyncTARepo(async_db_session)
    await repo.add_to_watchlist("Apt41", "default")
    await repo.add_to_watchlist("OtherGroup", "acme")

    # P7c: nama + alias entitas yang di-watch, huruf kecil (pencocokan `ioc_ta_links`)
    names = await repo.get_watchlist_names_unscoped()
    assert sorted(names) == ["apt41", "othergroup"]


async def test_save_and_get_profile(async_db_session: AsyncSession) -> None:
    repo = AsyncTAProfileRepo(async_db_session)
    profile_data = {
        "identity": {"primary_name": "APT41"},
        "motivation": {"primary_motivation": "espionage"},
    }

    saved = await repo.save_profile("APT41", profile_data)
    assert saved.actor_name == "APT41"

    fetched = await repo.get_profile("apt41")
    assert fetched is not None
    assert fetched.profile["identity"]["primary_name"] == "APT41"

    updated = await repo.save_profile("apt41", {"identity": {"primary_name": "APT41 updated"}})
    assert updated.id == saved.id
    refetched = await repo.get_profile("APT41")
    assert refetched is not None
    assert refetched.profile["identity"]["primary_name"] == "APT41 updated"


async def test_list_profiles_by_names(async_db_session: AsyncSession) -> None:
    repo = AsyncTAProfileRepo(async_db_session)
    await repo.save_profile("Apt41", {})
    await repo.save_profile("Turla", {})

    rows = await repo.list_profiles_by_names(["apt41", "nonexistent"])
    assert len(rows) == 1
    assert rows[0].actor_name == "Apt41"


async def test_fetch_recent_news_matches_title_regex(async_db_session: AsyncSession) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    await article_repo.upsert(
        url="https://example.com/apt41-news",
        title="APT41 targets government network",
        source="s",
        posted_on=datetime.date.today() - datetime.timedelta(days=5),
    )
    await article_repo.upsert(
        url="https://example.com/unrelated",
        title="Unrelated vendor news",
        source="s",
        posted_on=datetime.date.today() - datetime.timedelta(days=5),
    )

    repo = AsyncTAProfileRepo(async_db_session)
    news = await repo.fetch_recent_news("APT41")
    assert len(news) == 1
    assert news[0]["title"].startswith("APT41")


async def test_get_timeline_dormancy_states(async_db_session: AsyncSession) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    recent = datetime.date.today() - datetime.timedelta(days=5)
    a1 = await article_repo.upsert(
        url="https://example.com/apt41-recent",
        title="APT41 hits target",
        source="s",
        posted_on=recent,
    )
    await article_repo.set_enrichment(a1, threat_actors=["Apt41"])

    repo = AsyncTAProfileRepo(async_db_session)
    timeline = await repo.get_timeline("Apt41", months=3)
    assert timeline["dormancy_state"] == "ACTIVE"
    assert sum(timeline["total_counts"]) == 1

    states = await repo.get_dormancy_states(["Apt41", "NeverSeen"])
    assert states["Apt41"] in ("ACTIVE", "RESURGENT")
    assert states["NeverSeen"] == "DORMANT"
