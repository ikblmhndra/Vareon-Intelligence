"""Pembaca repository P7c Task 11 di Postgres beneran: `mention_rows()` (entity_mentions join
entities, hanya entitas hidup) dan pembaca yang kini memakainya -- alias satu entitas dihitung
sebagai satu seri, entitas suppressed/tombstone tidak muncul, nama dari pengguna di-resolve lewat
`entity_aliases`, dan watchlist TA memakai `entity_watches`."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.models.entity import Entity
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from cti_core.db.repositories.entity import mention_rows
from cti_core.db.repositories.ta import AsyncTAProfileRepo, AsyncTARepo
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.entity_support import seed_entity

pytestmark = pytest.mark.asyncio

_TODAY = datetime.date.today()
_NO_DATES = {"posted_on_start": None, "posted_on_end": None}


async def _seed_actor(session: AsyncSession, name: str, *aliases: str) -> Entity:
    return await session.run_sync(
        lambda s: seed_entity(s, "intrusion-set", name, *aliases, source="galaxy")
    )


async def _article(session: AsyncSession, slug: str, **enrichment: object) -> int:
    repo = AsyncArticleRepo(session)
    a = await repo.upsert(
        url=f"https://example.com/mr-{slug}", title=slug, source="S", posted_on=_TODAY
    )
    await repo.set_enrichment(a, **enrichment)  # type: ignore[arg-type]
    return a.id


async def test_mention_rows_maps_reader_columns(async_db_session: AsyncSession) -> None:
    aid = await _article(
        async_db_session,
        "cols",
        countries=[("ID", "victim")],
        industries=["Finance & Insurance"],
        threat_actors=["Apt41"],
        ttps=[("T1059", "Command and Scripting Interpreter")],
    )
    sub = mention_rows()
    rows = (
        await async_db_session.execute(
            select(sub.c.type, sub.c.name, sub.c.external_id, sub.c.role, sub.c.method)
            .where(sub.c.article_id == aid)
            .order_by(sub.c.type)
        )
    ).all()
    assert [tuple(r) for r in rows] == [
        ("attack-pattern", "Command and Scripting Interpreter", "T1059", None, "llm"),
        ("identity", "Financial Services", "financial-services", None, "llm"),
        ("intrusion-set", "Apt41", None, None, "dictionary"),
        ("location", "Indonesia", "ID", "victim", "llm"),
    ]
    only = mention_rows("location")
    codes = (
        (await async_db_session.execute(select(only.c.external_id).where(only.c.article_id == aid)))
        .scalars()
        .all()
    )
    assert codes == ["ID"]


async def test_aliases_collapse_in_counts(async_db_session: AsyncSession) -> None:
    await _seed_actor(async_db_session, "APT29", "Cozy Bear")
    await _article(async_db_session, "a", threat_actors=["APT29"])
    await _article(async_db_session, "b", threat_actors=["Cozy Bear"])

    top = await AsyncDashboardRepo(async_db_session).top_threat_actors(limit=10, **_NO_DATES)
    assert top == [("APT29", 2)]


async def test_suppressed_hidden(async_db_session: AsyncSession) -> None:
    ent = await _seed_actor(async_db_session, "NoisyName")
    await _seed_actor(async_db_session, "RealActor")
    await _article(async_db_session, "s", threat_actors=["NoisyName", "RealActor"])
    await async_db_session.execute(
        update(Entity).where(Entity.id == ent.id).values(suppressed=True)
    )

    repo = AsyncDashboardRepo(async_db_session)
    assert await repo.top_threat_actors(limit=10, **_NO_DATES) == [("RealActor", 1)]
    assert await repo.unique_threat_actor_count(**_NO_DATES) == 1
    options = await AsyncArticleRepo(async_db_session).get_filter_options()
    assert options["threat_actors"] == ["RealActor"]


async def test_merged_tombstone_hidden(async_db_session: AsyncSession) -> None:
    tomb = await _seed_actor(async_db_session, "OldName")
    live = await _seed_actor(async_db_session, "NewName")
    await _article(async_db_session, "m", threat_actors=["OldName"])
    # tombstone tanpa repoint mention: pembaca tetap tidak boleh menampilkannya
    await async_db_session.execute(
        update(Entity).where(Entity.id == tomb.id).values(merged_into_id=live.id)
    )
    assert await AsyncDashboardRepo(async_db_session).top_threat_actors(**_NO_DATES) == []


async def test_actor_filter_resolves_aliases(async_db_session: AsyncSession) -> None:
    await _seed_actor(async_db_session, "Transparent Tribe", "APT36")
    aid = await _article(async_db_session, "f", threat_actors=["Transparent Tribe"])

    articles, total = await AsyncArticleRepo(async_db_session).list_filtered(
        threat_actors=["apt36"]
    )
    assert total == 1 and [a.id for a in articles] == [aid]


async def test_watchlist_by_alias(async_db_session: AsyncSession) -> None:
    await AsyncClientRepo(async_db_session).ensure_default()
    await _seed_actor(async_db_session, "Transparent Tribe", "APT36")
    repo = AsyncTARepo(async_db_session)

    assert await repo.add_to_watchlist("apt36", "default") == {"success": True}
    assert await repo.add_to_watchlist("Transparent Tribe", "default") == {
        "success": False,
        "reason": "already_watched",
    }
    assert await repo.is_watched("Transparent Tribe", "default") is True
    assert await repo.is_watched("APT36", "default") is True
    assert await repo.get_watchlist_names("default") == ["Transparent Tribe"]
    assert sorted(await repo.get_watchlist_names_unscoped()) == ["apt36", "transparent tribe"]

    await _article(async_db_session, "w", threat_actors=["APT36"])
    hits = await AsyncDashboardRepo(async_db_session).watchlist_hit_count(
        client_id="default", posted_on_start=None
    )
    assert hits == 1

    assert await repo.remove_from_watchlist("TRANSPARENT TRIBE", "default") is True
    assert await repo.is_watched("apt36", "default") is False


async def test_whitelist_suppresses_entity(async_db_session: AsyncSession) -> None:
    ent = await _seed_actor(async_db_session, "Cobalt", "Cobalt Group")
    repo = AsyncTARepo(async_db_session)
    await repo.add_group("Cobalt")
    groups, _ = await repo.list_groups()
    await repo.delete_group(groups[0].id, "cobalt group")

    await async_db_session.refresh(ent)
    assert ent.suppressed is True
    items, total = await repo.list_whitelist()
    assert total == 1 and [w.name for w in items] == ["cobalt"]
    assert await repo.add_group("COBALT") == {"success": False, "reason": "whitelisted"}

    assert await repo.remove_from_whitelist("Cobalt") is True
    await async_db_session.refresh(ent)
    assert ent.suppressed is False


async def test_profile_by_alias(async_db_session: AsyncSession) -> None:
    await _seed_actor(async_db_session, "Transparent Tribe", "APT36")
    repo = AsyncTAProfileRepo(async_db_session)
    await repo.save_profile("apt36", {"summary": "x"})

    row = await repo.get_profile("Transparent Tribe")
    assert row is not None and row.actor_name == "Transparent Tribe"
    assert row.profile == {"summary": "x"}
    await repo.save_profile("TRANSPARENT TRIBE", {"summary": "y"})
    rows = await repo.list_profiles_by_names(["APT36"])
    assert [(r.actor_name, r.profile) for r in rows] == [("APT36", {"summary": "y"})]


async def test_list_profiles_by_names_keeps_caller_names(async_db_session: AsyncSession) -> None:
    """Kontrak v1: pemanggil (crossref, diamond, geopolitical) mengindeks hasil dengan
    `actor_name.lower()` lalu mencari pakai nama masukannya sendiri."""
    await _seed_actor(async_db_session, "Transparent Tribe", "APT36")
    await _seed_actor(async_db_session, "NoProfile")
    repo = AsyncTAProfileRepo(async_db_session)
    await repo.save_profile("Transparent Tribe", {"summary": "tt"})

    rows = await repo.list_profiles_by_names(["apt36", "Transparent Tribe", "NoProfile", "x"])
    by_lower = {r.actor_name.lower(): r.profile for r in rows}
    assert by_lower == {"apt36": {"summary": "tt"}, "transparent tribe": {"summary": "tt"}}


async def test_whitelist_added_date_is_stable(async_db_session: AsyncSession) -> None:
    ent = await _seed_actor(async_db_session, "Quiet")
    repo = AsyncTARepo(async_db_session)
    await repo.delete_group(0, "Quiet")
    (first,), _ = await repo.list_whitelist()

    # sunting entitas (rename) menggeser updated_at, bukan tanggal masuk whitelist
    await async_db_session.execute(
        update(Entity)
        .where(Entity.id == ent.id)
        .values(description="edited", updated_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC))
    )
    (again,), _ = await repo.list_whitelist(sort_by="added_date", sort_dir="desc")
    assert again.added_date == first.added_date
    assert again.added_date.year != 2030


async def test_whitelist_without_audit_uses_created_at(async_db_session: AsyncSession) -> None:
    """Suppress dari migrasi (`ta_whitelist` lama) tidak punya audit: tanggal = created_at."""
    ent = await _seed_actor(async_db_session, "Migrated")
    await async_db_session.execute(
        update(Entity)
        .where(Entity.id == ent.id)
        .values(suppressed=True, updated_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC))
    )
    await async_db_session.refresh(ent)
    (row,), _ = await AsyncTARepo(async_db_session).list_whitelist()
    assert row.added_date == ent.created_at


async def test_ta_stats_in_news_matches_group_aliases(async_db_session: AsyncSession) -> None:
    await _seed_actor(async_db_session, "Transparent Tribe", "APT36")
    repo = AsyncTARepo(async_db_session)
    await repo.add_group("apt36")  # nama grup = alias, bukan nama entitas
    await _article(async_db_session, "st", threat_actors=["Transparent Tribe"])

    stats = await repo.get_ta_stats()
    assert stats["top_in_news"] == [{"name": "Transparent Tribe", "count": 1}]
