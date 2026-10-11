"""Integration test `AsyncNewsletterRepo` -- Postgres REAL
(testcontainers). Fase 7.3 (router `newsletter`, Bagian 4); kolom periode dan cache ringkasan
artikel dari ROADMAP #22 (PR 5)."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.models.article import Article
from cti_core.db.models.newsletter import NewsletterArticleSummary
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
