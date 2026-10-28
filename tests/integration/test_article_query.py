"""Integration test `AsyncArticleRepo.list_filtered`/`get_filter_options` --
Postgres REAL (testcontainers). Fase 7.3 (router `articles`)."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.models.story import Story
from cti_core.db.repositories.article import AsyncArticleRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _seed(repo: AsyncArticleRepo) -> dict[str, int]:
    """Korpus kecil (5 artikel) yang nutupin tiap filter -- dipakai ulang
    tiap test di modul ini, bukan diulang per-test."""
    a1 = await repo.upsert(
        url="https://example.com/apt41-philippines",
        title="China-linked APT41 breaches Philippine government network",
        source="gbhacker",
        posted_on=datetime.date(2026, 9, 17),
        news_type="apac",
        confidence_score=100,
    )
    await repo.set_enrichment(
        a1,
        countries=[("PH", "victim"), ("CN", "actor")],
        industries=["Government & Public Sector"],
        threat_actors=["Apt41"],
        ttps=[("T1574", "Hijack Execution Flow")],
    )

    a2 = await repo.upsert(
        url="https://example.com/zero-trust-best-practices",
        title="Best practices for implementing Zero Trust network segmentation",
        source="gbhacker",
        posted_on=datetime.date(2026, 9, 15),
        news_type="Security Technology & Best Practices",
        confidence_score=90,
    )
    await repo.set_enrichment(
        a2, industries=["Information Technology & Software", "Finance & Insurance"]
    )

    a3 = await repo.upsert(
        url="https://example.com/global-adversarial-ai",
        title="GTIG AI Threat Tracker: adversarial AI evolution",
        source="Mandiant (Google Cloud Threat Intelligence)",
        posted_on=datetime.date(2026, 9, 8),
        news_type="global",
        confidence_score=70,
    )
    await repo.set_enrichment(a3, industries=["General"], countries=[("US", "mentioned")])

    a4 = await repo.upsert(
        url="https://example.com/healthcare-cn-actor",
        title="Public and Private Medical Community Targeted",
        source="Bitdefender Labs",
        posted_on=datetime.date(2026, 8, 1),
        news_type="apac",
        confidence_score=80,
    )
    await repo.set_enrichment(
        a4,
        countries=[("CN", "actor"), ("PH", "victim")],
        industries=["Healthcare & Life Sciences", "Government & Public Sector"],
        threat_actors=["Apt41"],
    )

    a5 = await repo.upsert(
        url="https://example.com/no-enrichment",
        title="Unrelated vendor product update",
        source="VendorBlog",
        posted_on=None,
        news_type=None,
        confidence_score=None,
    )

    return {"a1": a1.id, "a2": a2.id, "a3": a3.id, "a4": a4.id, "a5": a5.id}


async def test_list_filtered_no_filters_returns_all_paginated(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    await _seed(repo)

    articles, total = await repo.list_filtered(page=1, page_size=2)
    assert total == 5
    assert len(articles) == 2
    # posted_on desc, NULL last -- a1 (2026-09-17) duluan
    assert articles[0].title.startswith("China-linked APT41")


async def test_list_filtered_by_posted_on_range(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, total = await repo.list_filtered(
        posted_on_start=datetime.date(2026, 9, 10), posted_on_end=datetime.date(2026, 9, 20)
    )
    assert total == 2
    assert {a.id for a in articles} == {ids["a1"], ids["a2"]}


async def test_list_filtered_by_industry(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, total = await repo.list_filtered(industries=["Government & Public Sector"])
    assert total == 2
    assert {a.id for a in articles} == {ids["a1"], ids["a4"]}


async def test_list_filtered_by_country_mentioned_role(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, total = await repo.list_filtered(countries=["US"])
    assert total == 1
    assert articles[0].id == ids["a3"]


async def test_list_filtered_by_country_matches_any_role(async_db_session: AsyncSession) -> None:
    """QA BUG-B1: filter `country` (dan panel "ID News" yang numpang filter
    ini) dulu cuma nyocokin role "mentioned" -- padahal `mentioned_countries`
    Mongo lama = gabungan regex + victim + actor, dan mayoritas data negara
    sekarang ada di role victim. PH cuma victim (a1/a4), CN cuma actor."""
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, total = await repo.list_filtered(countries=["PH"])
    assert total == 2
    assert {a.id for a in articles} == {ids["a1"], ids["a4"]}

    articles, total = await repo.list_filtered(countries=["CN"])
    assert total == 2
    assert {a.id for a in articles} == {ids["a1"], ids["a4"]}

    # Multi-negara lintas role: a1 cocok di DUA baris (PH victim + CN actor)
    # tapi tetap muncul sekali, total gak dobel.
    articles, total = await repo.list_filtered(countries=["PH", "CN", "US"])
    assert total == 3
    assert sorted(a.id for a in articles) == sorted([ids["a1"], ids["a3"], ids["a4"]])


async def test_list_filtered_by_victim_country(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, total = await repo.list_filtered(victim_countries=["PH"])
    assert total == 2
    assert {a.id for a in articles} == {ids["a1"], ids["a4"]}


async def test_list_filtered_by_actor_country(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, total = await repo.list_filtered(actor_countries=["CN"])
    assert total == 2
    assert {a.id for a in articles} == {ids["a1"], ids["a4"]}


async def test_list_filtered_by_source(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, total = await repo.list_filtered(sources=["Bitdefender Labs"])
    assert total == 1
    assert articles[0].id == ids["a4"]


async def test_list_filtered_by_news_type(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, total = await repo.list_filtered(news_types=["apac"])
    assert total == 2
    assert {a.id for a in articles} == {ids["a1"], ids["a4"]}


async def test_list_filtered_by_threat_actor_case_insensitive_exact(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, total = await repo.list_filtered(threat_actors=["apt41"])
    assert total == 2
    assert {a.id for a in articles} == {ids["a1"], ids["a4"]}

    # substring TIDAK boleh cocok -- exact match doang, port dari regex
    # ^...$ Mongo lama.
    _, total_substring = await repo.list_filtered(threat_actors=["apt"])
    assert total_substring == 0


async def test_list_filtered_by_search_matches_title_or_source(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    by_title, total1 = await repo.list_filtered(search="zero trust")
    assert total1 == 1
    assert by_title[0].id == ids["a2"]

    by_source, total2 = await repo.list_filtered(search="bitdefender")
    assert total2 == 1
    assert by_source[0].id == ids["a4"]


async def test_list_filtered_by_ttps(async_db_session: AsyncSession) -> None:
    """`ttps` (Fase 7.3, router `pir`) -- filter `ArticleTTP.ttp_id`."""
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, total = await repo.list_filtered(ttps=["T1574"])
    assert total == 1
    assert articles[0].id == ids["a1"]

    _, total_missing = await repo.list_filtered(ttps=["T9999"])
    assert total_missing == 0


async def test_list_filtered_by_title_keyword_or(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, total = await repo.list_filtered(title_keywords=["APT41", "Medical"])
    assert total == 2
    assert {a.id for a in articles} == {ids["a1"], ids["a4"]}


async def test_list_filtered_combines_keyword_and_search_with_and(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    # keyword "APT41" (cocok a1/a4) AND search "philippine" (cocok a1 doang
    # by title) -- irisan harus a1 doang.
    articles, total = await repo.list_filtered(title_keywords=["APT41"], search="philippine")
    assert total == 1
    assert articles[0].id == ids["a1"]


async def test_list_filtered_join_does_not_duplicate_article_with_multiple_matches(
    async_db_session: AsyncSession,
) -> None:
    """a1 punya country VICTIM=PH DAN ACTOR=CN -- filter victim_country=[PH]
    doang join SATU tabel country sekali, gak boleh dobel row walau artikel
    punya banyak country row total."""
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, total = await repo.list_filtered(victim_countries=["PH"])
    result_ids = [a.id for a in articles]
    assert result_ids.count(ids["a1"]) == 1
    assert total == len(articles)


async def test_list_filtered_article_without_enrichment_has_empty_relations(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    articles, _ = await repo.list_filtered(sources=["VendorBlog"])
    assert len(articles) == 1
    a5 = articles[0]
    assert a5.id == ids["a5"]
    assert a5.countries == []
    assert a5.industries == []
    assert a5.posted_on is None


async def test_get_filter_options_returns_distinct_sorted_values(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    await _seed(repo)

    options = await repo.get_filter_options()
    assert options["sources"] == sorted(options["sources"])
    assert "gbhacker" in options["sources"]
    assert "Government & Public Sector" in options["industries"]
    assert "Apt41" in options["threat_actors"]
    assert options["date_range"]["min"] == "2026-08-01"
    assert options["date_range"]["max"] == "2026-09-17"


async def test_get_filter_options_countries_include_every_role(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    await _seed(repo)

    options = await repo.get_filter_options()
    # QA BUG-B1: PH (victim) & CN (actor) WAJIB ada -- opsi dropdown harus
    # sama semantik sama filter `country` (role apa pun), sorted & unik.
    assert options["countries"] == ["CN", "PH", "US"]


async def test_get_by_id_returns_none_for_missing(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    assert await repo.get_by_id(999999) is None


async def test_get_by_id_returns_article(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    fetched = await repo.get_by_id(ids["a1"])
    assert fetched is not None
    assert fetched.title.startswith("China-linked APT41")


async def test_get_by_ids_returns_dict_keyed_by_id(async_db_session: AsyncSession) -> None:
    """Fase 7.3 (router `newsletter`, Bagian 4) -- port `fetch_articles_by_ids()`."""
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed(repo)

    rows = await repo.get_by_ids([ids["a1"], ids["a3"], 999999])
    assert set(rows.keys()) == {ids["a1"], ids["a3"]}
    assert rows[ids["a1"]].title.startswith("China-linked APT41")


async def test_get_by_ids_empty_list_returns_empty_dict(async_db_session: AsyncSession) -> None:
    repo = AsyncArticleRepo(async_db_session)
    assert await repo.get_by_ids([]) == {}


async def test_list_filtered_priority_sort(async_db_session: AsyncSession) -> None:
    """P6 5.2: urutan prioritas = `priority_score` (NULL terakhir), lalu terbaru, lalu id.
    `confirmed_incident` bukan kunci pertama lagi (sudah +25 di dalam priority)."""
    repo = AsyncArticleRepo(async_db_session)
    day = datetime.date(2026, 9, 20)
    specs = {
        "a": dict(confirmed_incident=False, priority_score=130),
        "b": dict(confirmed_incident=True, priority_score=80),
        "c": dict(confirmed_incident=True, priority_score=None),
        "d": dict(confirmed_incident=False, priority_score=80),
    }
    ids: dict[str, int] = {}
    for i, (key, s) in enumerate(specs.items()):
        art = await repo.upsert(
            url=f"https://example.com/prio-{key}",
            title=f"prio {key}",
            source="S",
            posted_on=day - datetime.timedelta(days=i),
            **s,
        )
        ids[key] = art.id

    prio, _ = await repo.list_filtered(sort="priority")
    # b dan d seri di 80: b lebih baru.
    assert [a.id for a in prio] == [ids["a"], ids["b"], ids["d"], ids["c"]]
    recent, _ = await repo.list_filtered()
    assert [a.id for a in recent] == [ids["a"], ids["b"], ids["c"], ids["d"]]

    confirmed, total = await repo.list_filtered(confirmed_only=True)
    assert total == 2
    assert ids["a"] not in [a.id for a in confirmed]


async def _seed_story_priority(repo: AsyncArticleRepo, session: AsyncSession) -> dict[str, int]:
    """Satu story berisi tiga anggota (prioritas 90/120/60) plus dua artikel lepas (100/50).
    Tiap artikel punya dua baris industri yang sama-sama cocok dengan filter, supaya jalur
    `has_join` + `.distinct()` ikut teruji."""
    now = datetime.datetime(2026, 9, 20, tzinfo=datetime.UTC)
    story = Story(title="story", lead_source="S", first_seen_at=now, last_seen_at=now)
    session.add(story)
    await session.flush()
    specs = {
        "m90": (90, story.id),
        "m120": (120, story.id),
        "m60": (60, story.id),
        "s100": (100, None),
        "s50": (50, None),
    }
    ids: dict[str, int] = {}
    for i, (key, (prio, story_id)) in enumerate(specs.items()):
        art = await repo.upsert(
            url=f"https://example.com/story-prio-{key}",
            title=f"story prio {key}",
            source="S",
            posted_on=datetime.date(2026, 9, 20) - datetime.timedelta(days=i),
            priority_score=prio,
            story_id=story_id,
        )
        await repo.set_enrichment(art, industries=["Finance & Insurance", "General"])
        ids[key] = art.id
    return ids


async def test_list_filtered_priority_keeps_one_article_per_story(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed_story_priority(repo, async_db_session)

    prio, total = await repo.list_filtered(sort="priority")

    assert [a.id for a in prio] == [ids["m120"], ids["s100"], ids["s50"]]
    assert total == 3


async def test_list_filtered_priority_collapse_with_join_filter_has_no_duplicates(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed_story_priority(repo, async_db_session)

    prio, total = await repo.list_filtered(
        sort="priority", industries=["Finance & Insurance", "General"]
    )

    assert [a.id for a in prio] == [ids["m120"], ids["s100"], ids["s50"]]
    assert total == 3


async def test_list_filtered_priority_collapse_paginates_collapsed_rows(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed_story_priority(repo, async_db_session)

    page2, total = await repo.list_filtered(sort="priority", page=2, page_size=2)

    assert [a.id for a in page2] == [ids["s50"]]
    assert total == 3


async def test_list_filtered_recent_does_not_collapse_stories(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed_story_priority(repo, async_db_session)

    recent, total = await repo.list_filtered()

    assert [a.id for a in recent] == list(ids.values())
    assert total == 5


async def test_list_top_between_orders_by_priority_without_collapse(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    ids = await _seed_story_priority(repo, async_db_session)

    top, total = await repo.list_top_between(
        datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), limit=10
    )

    assert total == 5
    assert [a.id for a in top] == [
        ids["m120"],
        ids["s100"],
        ids["m90"],
        ids["m60"],
        ids["s50"],
    ]
