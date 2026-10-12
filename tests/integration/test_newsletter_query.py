"""Integration test `AsyncNewsletterRepo` -- Postgres REAL
(testcontainers). Fase 7.3 (router `newsletter`, Bagian 4); kolom periode dan cache ringkasan
artikel dari ROADMAP #22 (PR 5)."""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from cti_api.services import campaign as campaign_service
from cti_api.services import newsletter_suggestion
from cti_core.db.models.article import Article
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.newsletter import NewsletterArticleSummary, NewsletterSuggestion
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from cti_core.db.repositories.techstack import AsyncTechStackRepo
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.newsletter_stubs import no_campaigns

pytestmark = pytest.mark.asyncio

_SUMMARY = {
    "key_points": ["poin satu", "poin dua"],
    "summary": "ringkasan",
    "body_source": "fetched",
    "iocs": {"ips": ["203.0.113.77"]},
    "cve_ids": ["CVE-2026-1111"],
    "model": "stub-model",
    "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


async def _article(session: AsyncSession, n: int = 1) -> int:
    article = await AsyncArticleRepo(session).upsert(
        url=f"https://example.com/cache-{n}", title=f"Cache story {n}", source="gbhackers"
    )
    return article.id


async def test_save_and_get_by_id(async_db_session: AsyncSession) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    row = await repo.save(
        week=38,
        year=2026,
        generated_at="2026-09-19 10:00 UTC",
        created_by="analyst1",
        html="<html>digest</html>",
        sections={"highlight": {"title": "t1"}, "apac": [], "global_news": [], "indonesia": []},
    )
    assert row.id is not None

    fetched = await repo.get_by_id(row.id)
    assert fetched is not None
    assert fetched.week == 38
    assert fetched.sections["highlight"]["title"] == "t1"


async def test_get_html(async_db_session: AsyncSession) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    row = await repo.save(
        week=1,
        year=2026,
        generated_at="x",
        created_by="a",
        html="<html>hi</html>",
        sections={},
    )
    assert await repo.get_html(row.id) == "<html>hi</html>"
    assert await repo.get_html(999999) is None


async def test_list_all_newest_first_paginated(async_db_session: AsyncSession) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    for week in (1, 2, 3):
        await repo.save(
            week=week, year=2026, generated_at="x", created_by="a", html="<html/>", sections={}
        )

    rows, total = await repo.list_all(page=1, page_size=2)
    assert total == 3
    assert len(rows) == 2
    assert rows[0].week == 3  # created_at desc -- terakhir disimpen duluan


async def test_paywall_hint_upsert_and_list(async_db_session: AsyncSession) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    await repo.upsert_paywall_hint("example.com", last_seen="2026-09-18T00:00:00Z")
    await repo.upsert_paywall_hint("example.com", last_seen="2026-09-19T00:00:00Z")

    hint = await repo.get_paywall_hint("example.com")
    assert hint is not None
    assert hint.last_seen == "2026-09-19T00:00:00Z"

    hints = await repo.get_all_paywall_hints()
    assert hints["example.com"]["paywall_likely"] is True
    assert hints["example.com"]["last_seen"] == "2026-09-19T00:00:00Z"


async def test_get_all_paywall_hints_empty(async_db_session: AsyncSession) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    assert await repo.get_all_paywall_hints() == {}


async def test_save_stores_the_period_and_leaves_it_null_when_not_given(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    with_period = await repo.save(
        week=45,
        year=2026,
        period_start=datetime.date(2026, 10, 1),
        period_end=datetime.date(2026, 10, 31),
        generated_at="2026-11-02 02:00 UTC",
        created_by="analyst1",
        html="<html/>",
        sections={},
    )
    without = await repo.save(
        week=39, year=2026, generated_at="x", created_by="a", html="<html/>", sections={}
    )

    fetched = await repo.get_by_id(with_period.id)
    assert fetched is not None
    assert (fetched.period_start, fetched.period_end) == (
        datetime.date(2026, 10, 1),
        datetime.date(2026, 10, 31),
    )
    # `week`/`year` tetap diisi apa adanya: kolom itu NOT NULL dan UI histori lama membacanya.
    assert (fetched.week, fetched.year) == (45, 2026)
    legacy = await repo.get_by_id(without.id)
    assert legacy is not None
    assert (legacy.period_start, legacy.period_end) == (None, None)


async def test_article_summary_roundtrip_keeps_every_field(async_db_session: AsyncSession) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    article_id = await _article(async_db_session)
    assert await repo.get_article_summary(article_id, "en") is None

    await repo.upsert_article_summary(article_id=article_id, language="en", **_SUMMARY)

    row = await repo.get_article_summary(article_id, "en")
    assert row is not None
    assert row.article_id == article_id
    assert row.language == "en"
    assert row.key_points == _SUMMARY["key_points"]
    assert row.summary == "ringkasan"
    assert row.body_source == "fetched"
    assert row.iocs == {"ips": ["203.0.113.77"]}
    assert row.cve_ids == ["CVE-2026-1111"]
    assert row.model == "stub-model"
    assert row.token_usage["total_tokens"] == 15
    assert row.created_at is not None


async def test_upserting_the_same_article_and_language_overwrites_one_row(
    async_db_session: AsyncSession,
) -> None:
    """`regenerate` = upsert kedua: harus menimpa, bukan menambah baris atau kena unique."""
    repo = AsyncNewsletterRepo(async_db_session)
    article_id = await _article(async_db_session)
    await repo.upsert_article_summary(article_id=article_id, language="en", **_SUMMARY)
    # Objek ORM sudah termuat di sesi ini: pembacaan sesudah upsert tidak boleh memberi data basi.
    stale = await repo.get_article_summary(article_id, "en")
    assert stale is not None and stale.summary == "ringkasan"

    newer = {**_SUMMARY, "summary": "ringkasan baru", "cve_ids": [], "body_source": "metadata"}
    await repo.upsert_article_summary(article_id=article_id, language="en", **newer)

    row = await repo.get_article_summary(article_id, "en")
    assert row is not None
    assert (row.summary, row.cve_ids, row.body_source) == ("ringkasan baru", [], "metadata")
    count = (
        await async_db_session.execute(select(func.count()).select_from(NewsletterArticleSummary))
    ).scalar_one()
    assert count == 1


async def test_summaries_are_kept_per_language(async_db_session: AsyncSession) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    article_id = await _article(async_db_session)
    await repo.upsert_article_summary(article_id=article_id, language="en", **_SUMMARY)
    await repo.upsert_article_summary(
        article_id=article_id, language="id", **{**_SUMMARY, "summary": "ringkasan bahasa"}
    )

    en = await repo.get_article_summary(article_id, "en")
    idn = await repo.get_article_summary(article_id, "id")
    assert en is not None and idn is not None
    assert (en.summary, idn.summary) == ("ringkasan", "ringkasan bahasa")
    assert await repo.get_article_summary(article_id, "fr") is None


async def test_get_article_summaries_returns_only_the_cached_ones_in_one_call(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    cached_a = await _article(async_db_session, 1)
    uncached = await _article(async_db_session, 2)
    cached_b = await _article(async_db_session, 3)
    await repo.upsert_article_summary(article_id=cached_a, language="en", **_SUMMARY)
    await repo.upsert_article_summary(article_id=cached_b, language="en", **_SUMMARY)
    await repo.upsert_article_summary(article_id=uncached, language="id", **_SUMMARY)

    found = await repo.get_article_summaries([cached_a, uncached, cached_b], "en")

    assert sorted(found) == sorted([cached_a, cached_b])
    assert await repo.get_article_summaries([], "en") == {}


async def test_summary_row_goes_away_with_its_article(async_db_session: AsyncSession) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    article_id = await _article(async_db_session)
    await repo.upsert_article_summary(article_id=article_id, language="en", **_SUMMARY)

    await async_db_session.execute(delete(Article).where(Article.id == article_id))

    count = (
        await async_db_session.execute(select(func.count()).select_from(NewsletterArticleSummary))
    ).scalar_one()
    assert count == 0


# ── Saran konten bulanan (ROADMAP #22, PR 7) ─────────────────────────────────────────────────────

_OCT = (datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
_SEP = (datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))

_ITEM = {
    "article_id": 11,
    "section": "indonesia",
    "tier": "highlight",
    "rank": 1,
    "reasons": [{"code": "kev", "text": "Mentions CVE-2026-1111 in the CISA KEV catalog"}],
}


async def _suggest(
    repo: AsyncNewsletterRepo, period: tuple[datetime.date, datetime.date], **kwargs: Any
) -> NewsletterSuggestion:
    return await repo.upsert_suggestion(period_start=period[0], period_end=period[1], **kwargs)


async def test_suggestion_roundtrip_keeps_every_field(async_db_session: AsyncSession) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    assert await repo.get_suggestion(*_OCT) is None

    saved = await _suggest(repo, _OCT, items=[_ITEM])

    row = await repo.get_suggestion(*_OCT)
    assert row is not None and row.id == saved.id
    assert (row.period_start, row.period_end) == _OCT
    assert row.items == [_ITEM]
    # Isian ringkasan sengaja kosong sampai PR 8; kosong = "belum ada", bukan NULL.
    assert (row.summary_text, row.summary_meta) == ("", {})
    assert row.created_at is not None


async def test_the_period_pair_is_unique_in_the_database(async_db_session: AsyncSession) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    await _suggest(repo, _OCT, items=[])

    duplicate = NewsletterSuggestion(
        period_start=_OCT[0], period_end=_OCT[1], items=[], summary_text="", summary_meta={}
    )
    with pytest.raises(IntegrityError):
        async with async_db_session.begin_nested():
            async_db_session.add(duplicate)
            await async_db_session.flush()


async def test_rebuilding_the_same_window_replaces_the_row_entirely(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    first = await _suggest(
        repo, _OCT, items=[_ITEM], summary_text="paragraf lama", summary_meta={"weeks": [40]}
    )
    await async_db_session.execute(
        text("UPDATE newsletter_suggestions SET created_at = '2020-01-01 00:00:00+00'")
    )

    newer_item = {**_ITEM, "article_id": 12, "tier": "full", "rank": 2}
    second = await _suggest(repo, _OCT, items=[newer_item])

    assert second.id == first.id  # baris yang sama ditimpa, bukan baris baru
    row = await repo.get_suggestion(*_OCT)
    assert row is not None
    assert row.items == [newer_item]
    assert (row.summary_text, row.summary_meta) == ("", {})  # ringkasan ikut dibangun ulang
    assert row.created_at.year >= 2026  # `created_at` = waktu dibangun, ikut diperbarui
    count = (
        await async_db_session.execute(select(func.count()).select_from(NewsletterSuggestion))
    ).scalar_one()
    assert count == 1


async def test_only_the_exact_window_matches_and_other_windows_are_separate_rows(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    await _suggest(repo, _OCT, items=[_ITEM])
    await _suggest(repo, _SEP, items=[])

    assert (
        await repo.get_suggestion(datetime.date(2026, 10, 1), datetime.date(2026, 10, 30)) is None
    )
    assert (
        await repo.get_suggestion(datetime.date(2026, 10, 2), datetime.date(2026, 10, 31)) is None
    )
    sep = await repo.get_suggestion(*_SEP)
    assert sep is not None and sep.items == []
    count = (
        await async_db_session.execute(select(func.count()).select_from(NewsletterSuggestion))
    ).scalar_one()
    assert count == 2


async def test_latest_suggestion_is_the_window_that_ends_last_not_the_last_written(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncNewsletterRepo(async_db_session)
    assert await repo.latest_suggestion() is None

    await _suggest(repo, _OCT, items=[_ITEM])
    await _suggest(repo, _SEP, items=[])  # bulan lama dibangun belakangan (rebuild manual)

    latest = await repo.latest_suggestion()
    assert latest is not None
    assert (latest.period_start, latest.period_end) == _OCT


# ── Kandidat dan pembangunan saran dari DB (ROADMAP #22, PR 7) ───────────────────────────────────


async def _seed(
    session: AsyncSession,
    n: int,
    posted_on: datetime.date | None,
    *,
    title: str | None = None,
    source: str = "CISA",
    countries: tuple[tuple[str, str], ...] = (),
    **fields: Any,
) -> Article:
    """Judul default unik per artikel: dedup menyatukan judul yang mirip."""
    repo = AsyncArticleRepo(session)
    article = await repo.upsert(
        url=f"https://example.com/suggest-{n}",
        title=title or f"suggest{n:03d} headline{n:03d}",
        source=source,
        posted_on=posted_on,
        **fields,
    )
    if countries:
        await repo.set_enrichment(article, countries=list(countries))
    return article


async def test_candidates_are_the_articles_posted_inside_the_window(
    async_db_session: AsyncSession,
) -> None:
    day = datetime.date
    await _seed(async_db_session, 1, day(2026, 9, 30))
    first = await _seed(async_db_session, 2, day(2026, 10, 1))
    middle = await _seed(
        async_db_session,
        3,
        day(2026, 10, 15),
        source="BleepingComputer",
        countries=(("ID", "victim"), ("ID", "mentioned"), ("SG", "mentioned"), ("CN", "actor")),
        confidence_score=90,
        confirmed_incident=True,
    )
    last = await _seed(async_db_session, 4, day(2026, 10, 31))
    await _seed(async_db_session, 5, day(2026, 11, 1))
    await _seed(async_db_session, 6, None)

    with no_campaigns():
        candidates = await newsletter_suggestion.load_candidates(async_db_session, *_OCT)

    assert {c.article_id for c in candidates} == {first.id, middle.id, last.id}
    got = next(c for c in candidates if c.article_id == middle.id)
    assert got.title == "suggest003 headline003"
    assert got.source == "BleepingComputer"
    assert got.posted_on == day(2026, 10, 15)
    assert (got.confidence_score, got.confirmed_incident) == (90, True)
    # Hanya role victim dan mentioned; negara actor tidak ikut (aturan section).
    assert got.victim_countries == ("ID",)
    assert got.mentioned_countries == ("ID", "SG")
    assert got.cluster_size == 1
    assert (got.kev_cves, got.poc_cves) == ((), ())


async def test_a_window_without_articles_has_no_candidates(async_db_session: AsyncSession) -> None:
    with no_campaigns():
        assert await newsletter_suggestion.load_candidates(async_db_session, *_OCT) == []


async def test_every_page_of_a_large_window_is_read(async_db_session: AsyncSession) -> None:
    for n in range(1, 8):
        await _seed(async_db_session, n, datetime.date(2026, 10, n))

    with no_campaigns(), patch.object(newsletter_suggestion, "PAGE_SIZE", 3):
        candidates = await newsletter_suggestion.load_candidates(async_db_session, *_OCT)

    assert len(candidates) == 7


async def test_candidates_read_the_values_analysts_have_overridden(
    async_db_session: AsyncSession,
) -> None:
    articles = AsyncArticleRepo(async_db_session)
    overridden = await _seed(
        async_db_session,
        1,
        datetime.date(2026, 10, 5),
        confidence_score=40,
        confirmed_incident=False,
    )
    await articles.set_overrides(overridden, confidence_score=95, confirmed_incident=True)
    garbage = await _seed(async_db_session, 2, datetime.date(2026, 10, 6), confidence_score=70)
    await articles.set_overrides(garbage, confidence_score="high")  # bukan angka: diabaikan

    with no_campaigns():
        candidates = await newsletter_suggestion.load_candidates(async_db_session, *_OCT)

    by_id = {c.article_id: c for c in candidates}
    assert (by_id[overridden.id].confidence_score, by_id[overridden.id].confirmed_incident) == (
        95,
        True,
    )
    assert by_id[garbage.id].confidence_score is None


async def test_cves_come_from_titles_and_ioc_links_and_carry_kev_and_poc(
    async_db_session: AsyncSession,
) -> None:
    await AsyncClientRepo(async_db_session).ensure_default()
    in_title = await _seed(
        async_db_session, 1, datetime.date(2026, 10, 5), title="Fortinet cve-2026-1001 exploited"
    )
    in_body = await _seed(async_db_session, 2, datetime.date(2026, 10, 6))
    untracked = await _seed(
        async_db_session, 3, datetime.date(2026, 10, 7), title="Flaw CVE-2026-1003 found"
    )
    false_positive = await _seed(
        async_db_session, 4, datetime.date(2026, 10, 8), title="Bug CVE-2026-1004"
    )
    for row in (
        CveTracker(cve_id="CVE-2026-1001", client_id="default", cisa_kev=True, poc_available=True),
        CveTracker(cve_id="CVE-2026-1002", client_id="default", poc_available=True),
        CveTracker(cve_id="CVE-2026-1004", client_id="default", cisa_kev=True),
    ):
        async_db_session.add(row)
    await async_db_session.flush()
    await AsyncCveFalsePositiveRepo(async_db_session).mark("CVE-2026-1004", "default")
    # CVE yang hanya ada di BODY lolos lewat IOC yang tersambung ke artikelnya.
    await AsyncIOCRepo(async_db_session).upsert(
        type="cve",
        value="CVE-2026-1002",
        source_url=in_body.url,
        source_name="CISA",
        article_id=in_body.id,
    )

    with no_campaigns():
        candidates = await newsletter_suggestion.load_candidates(async_db_session, *_OCT)

    by_id = {c.article_id: c for c in candidates}
    assert (by_id[in_title.id].kev_cves, by_id[in_title.id].poc_cves) == (
        ("CVE-2026-1001",),
        ("CVE-2026-1001",),
    )
    assert (by_id[in_body.id].kev_cves, by_id[in_body.id].poc_cves) == ((), ("CVE-2026-1002",))
    # CVE tidak di-track, atau FP oleh satu-satunya pemantaunya: tidak ada sinyal.
    for plain in (untracked, false_positive):
        assert (by_id[plain.id].kev_cves, by_id[plain.id].poc_cves) == ((), ())


async def test_cluster_size_counts_only_the_members_inside_the_window(
    async_db_session: AsyncSession,
) -> None:
    inside = [await _seed(async_db_session, n, datetime.date(2026, 10, n)) for n in (1, 2, 3)]
    after_window = await _seed(async_db_session, 4, datetime.date(2026, 11, 1))
    lone = await _seed(async_db_session, 5, datetime.date(2026, 10, 9))
    elsewhere = await _seed(async_db_session, 6, datetime.date(2026, 10, 10))
    campaigns = [
        {"member_article_ids": [a.id for a in inside] + [after_window.id]},
        # Tinggal satu anggota di jendela: bukan kampanye di jendela ini.
        {"member_article_ids": [lone.id, after_window.id]},
    ]

    with patch.object(newsletter_suggestion, "_campaigns", AsyncMock(return_value=campaigns)):
        candidates = await newsletter_suggestion.load_candidates(async_db_session, *_OCT)

    sizes = {c.article_id: c.cluster_size for c in candidates}
    assert [sizes[a.id] for a in inside] == [3, 3, 3]  # anggota 4 (Nov) tidak dihitung
    assert sizes[lone.id] == sizes[elsewhere.id] == 1
    assert after_window.id not in sizes


async def test_campaigns_are_read_back_from_today_to_the_period_start(
    async_db_session: AsyncSession,
) -> None:
    """`get_recent_campaigns` belum mengenal jendela (PR 2): `days` dihitung dari hari ini."""
    start = datetime.date.today() - datetime.timedelta(days=40)
    seen = AsyncMock(return_value=[])
    with patch.object(campaign_service, "get_recent_campaigns", seen):
        await newsletter_suggestion._campaigns(async_db_session, start)

    assert seen.await_args is not None
    assert seen.await_args.kwargs == {"days": 40, "min_size": 3}


async def test_real_campaign_clustering_feeds_cluster_size(async_db_session: AsyncSession) -> None:
    """Tanpa stub: `get_recent_campaigns` sungguhan (TF-IDF) pada tiga artikel kembar hari ini."""
    today = datetime.date.today()
    twins = [
        await _seed(
            async_db_session,
            n,
            today,
            title="Lazarus group targets cryptocurrency exchanges with new malware",
            source=f"Outlet {n}",
        )
        for n in (1, 2, 3)
    ]
    await _seed(async_db_session, 4, today, title="Quarterly earnings beat expectations broadly")

    candidates = await newsletter_suggestion.load_candidates(
        async_db_session, today - datetime.timedelta(days=3), today
    )

    sizes = {c.article_id: c.cluster_size for c in candidates}
    assert [sizes[a.id] for a in twins] == [3, 3, 3]


async def test_build_suggestion_ranks_with_the_signals_of_all_clients_and_stores_it(
    async_db_session: AsyncSession,
) -> None:
    clients = AsyncClientRepo(async_db_session)
    await clients.ensure_default()
    await clients.create(client_id="acme", name="Acme", countries=["fr"])
    await clients.update("default", name="Default", countries=["SG"])
    stack = AsyncTechStackRepo(async_db_session)
    await stack.create(name="Fortinet", client_id="acme")
    retired, _ = await stack.create(name="Paloalto", client_id="default")
    assert retired is not None
    await stack.set_active(retired.id, "default", False)  # nonaktif: tidak dipantau
    day = datetime.date(2026, 10, 12)
    france = await _seed(async_db_session, 1, day, countries=(("FR", "victim"),))
    singapore = await _seed(async_db_session, 2, day, countries=(("SG", "mentioned"),))
    tech = await _seed(async_db_session, 3, day, title="Fortinet appliances are being probed")
    retired_tech = await _seed(
        async_db_session, 4, day, title="Paloalto firewall flaw reported", source="Random Blog"
    )
    bare = await _seed(async_db_session, 5, day, source="Random Blog")  # tanpa sinyal apa pun

    with no_campaigns():
        row = await newsletter_suggestion.build_suggestion(async_db_session, *_OCT)

    stored = {item["article_id"]: item for item in row.items}
    codes = {i: [r["code"] for r in item["reasons"]] for i, item in stored.items()}
    assert "client_country" in codes[france.id]  # negara client acme, huruf kecil di DB
    assert "client_country" in codes[singapore.id]  # negara client default
    assert "monitored_tech" in codes[tech.id]  # entri aktif client acme
    assert retired_tech.id not in stored  # entri nonaktif tidak dihitung, dan tanpa sinyal lain
    assert bare.id not in stored
    assert stored[singapore.id]["section"] == "apac"
    assert [item["rank"] for item in row.items] == list(range(1, len(row.items) + 1))
    assert row.items == (await AsyncNewsletterRepo(async_db_session).get_suggestion(*_OCT)).items  # type: ignore[union-attr]


async def test_build_suggestion_replaces_the_previous_one_for_the_same_window(
    async_db_session: AsyncSession,
) -> None:
    day = datetime.date(2026, 10, 12)
    first = await _seed(async_db_session, 1, day, confirmed_incident=True)
    with no_campaigns():
        before = await newsletter_suggestion.build_suggestion(async_db_session, *_OCT)
    assert [i["article_id"] for i in before.items] == [first.id]

    second = await _seed(async_db_session, 2, day, confirmed_incident=True, confidence_score=100)
    with no_campaigns():
        after = await newsletter_suggestion.build_suggestion(async_db_session, *_OCT)

    assert after.id == before.id
    assert [i["article_id"] for i in after.items] == [second.id, first.id]
    count = (
        await async_db_session.execute(select(func.count()).select_from(NewsletterSuggestion))
    ).scalar_one()
    assert count == 1
