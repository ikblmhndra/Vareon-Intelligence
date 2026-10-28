"""Integration test `cti_core.db.repositories.assessment` (P6 Task 3) -- Postgres REAL.

Satu `facts_stmt` dipakai driver sync (psycopg) dan async (asyncpg), jadi sebagian test jalan
lewat `db_session` dan sebagian lewat `async_db_session`."""

from __future__ import annotations

import datetime
import hashlib
from typing import Any

import pytest
from cti_core.db.models.article import Article, ArticleThreatActor, ArticleTTP
from cti_core.db.models.article_cve import ArticleCve
from cti_core.db.models.auth import Client
from cti_core.db.models.cve import CveFalsePositive, CveTracker
from cti_core.db.models.indicator import Indicator, IndicatorSource
from cti_core.db.models.source_reliability import SourceReliabilityEntry
from cti_core.db.models.story import Story
from cti_core.db.repositories.assessment import (
    apply_assessments,
    apply_assessments_async,
    facts_from_row,
    facts_stmt,
)
from cti_core.db.repositories.story import StoryRepo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_NOW = datetime.datetime(2026, 10, 26, tzinfo=datetime.UTC)
_TODAY = _NOW.date()


def _sr(name: str, grade: str, kind: str | None, origin: str = "default") -> SourceReliabilityEntry:
    return SourceReliabilityEntry(
        source_name=name,
        analyst_name="system" if origin == "default" else "analyst1",
        reliability_grade=grade,
        credibility_code="3",
        admiralty_code=f"{grade}3",
        notes="",
        added_date=_TODAY,
        last_updated=_TODAY,
        origin=origin,
        content_kind=kind,
    )


def _article(url: str, source: str, **kw: Any) -> Article:
    return Article(
        url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        title=f"title {url}",
        source=source,
        **kw,
    )


async def _cols(session: AsyncSession, article_id: int) -> tuple[Any, ...]:
    row = (
        await session.execute(
            select(
                Article.reliability_grade,
                Article.credibility,
                Article.confidence_score,
                Article.priority_score,
                Article.score_reasons,
            ).where(Article.id == article_id)
        )
    ).one()
    return tuple(row)


def _cols_sync(session: Session, article_id: int) -> tuple[Any, ...]:
    row = session.execute(
        select(
            Article.reliability_grade,
            Article.credibility,
            Article.confidence_score,
            Article.priority_score,
            Article.score_reasons,
        ).where(Article.id == article_id)
    ).one()
    return tuple(row)


@pytest.mark.asyncio
async def test_bare_aggregator_article_is_c4(async_db_session: AsyncSession) -> None:
    s = async_db_session
    s.add(_sr("Hackernews", "C", "news"))
    art = _article("https://ex.com/bare", "Hackernews")
    s.add(art)
    await s.flush()

    result = await apply_assessments_async(s, [art.id])

    assert set(result) == {art.id}
    assert result[art.id].admiralty_code == "C4"
    assert (await _cols(s, art.id))[:4] == ("C", 4, 40, 40)


@pytest.mark.asyncio
async def test_empty_ids_returns_empty(async_db_session: AsyncSession) -> None:
    assert await apply_assessments_async(async_db_session, []) == {}


@pytest.mark.asyncio
async def test_suppressed_ioc_is_not_an_artefact(async_db_session: AsyncSession) -> None:
    s = async_db_session
    s.add(_sr("Hackernews", "C", "news"))
    art = _article("https://ex.com/ioc", "Hackernews")
    bad = Indicator(type="ip", value="10.0.0.1", auto_suppressed=True)
    s.add_all([art, bad])
    await s.flush()
    s.add(
        IndicatorSource(
            indicator_id=bad.id, article_id=art.id, url=art.url, source_name="Hackernews"
        )
    )
    await s.flush()

    assert (await apply_assessments_async(s, [art.id]))[art.id].credibility == 4

    good = Indicator(type="ip", value="10.0.0.2", auto_suppressed=False)
    s.add(good)
    await s.flush()
    s.add(
        IndicatorSource(
            indicator_id=good.id, article_id=art.id, url=art.url, source_name="Hackernews"
        )
    )
    await s.flush()

    assert (await apply_assessments_async(s, [art.id]))[art.id].credibility == 3
    assert (await _cols(s, art.id))[1] == 3


def test_story_with_three_sources_and_cve_is_1(db_session: Session) -> None:
    s = db_session
    s.add(_sr("Hackernews", "C", "news"))
    repo = StoryRepo(s)
    story_id = repo.create(title="t", source="Hackernews", cve_ids=set(), now=_NOW)
    arts = [
        _article(f"https://ex.com/story{i}", src, story_id=story_id)
        for i, src in enumerate(["Hackernews", "BleepingComputer", "SecurityWeek"])
    ]
    s.add_all(arts)
    s.flush()
    for a in arts:
        repo.attach(story_id, article_id=a.id, cve_ids=set(), now=_NOW, classify=None)
    target = arts[0]
    s.add(ArticleCve(article_id=target.id, cve_id="CVE-2026-0001"))
    s.flush()

    result = apply_assessments(s, [target.id])

    a = result[target.id]
    assert a.credibility == 1
    assert {"code": "corroboration", "points": 8} in a.reasons["priority"]
    assert _cols_sync(s, target.id)[1] == 1
    assert _cols_sync(s, target.id)[4] == a.reasons


@pytest.mark.asyncio
async def test_null_story_and_zero_source_count_count_as_one(
    async_db_session: AsyncSession,
) -> None:
    s = async_db_session
    story = Story(title="t", lead_source="x", first_seen_at=_NOW, last_seen_at=_NOW)
    s.add(story)
    await s.flush()
    loose = _article("https://ex.com/loose", "Hackernews")
    zero = _article("https://ex.com/zero", "Hackernews", story_id=story.id)
    s.add_all([loose, zero])
    await s.flush()

    rows = (await s.execute(facts_stmt([loose.id, zero.id]))).mappings().all()

    assert len(rows) == 2
    assert all(facts_from_row(r).story_source_count == 1 for r in rows)


@pytest.mark.asyncio
async def test_kev_ignores_false_positive_tracker_rows(async_db_session: AsyncSession) -> None:
    s = async_db_session
    s.add_all([Client(client_id="p6-a", name="A"), Client(client_id="p6-b", name="B")])
    s.add(_sr("Hackernews", "C", "news"))
    art = _article("https://ex.com/kev", "Hackernews")
    s.add(art)
    await s.flush()
    s.add(ArticleCve(article_id=art.id, cve_id="CVE-2026-0002"))
    # Baris client A: KEV tapi ditandai FP oleh client A sendiri -> tidak dihitung.
    s.add(CveTracker(cve_id="cve-2026-0002", client_id="p6-a", cisa_kev=True))
    s.add(CveFalsePositive(cve_id="cve-2026-0002", client_id="p6-a"))
    await s.flush()

    codes = [
        p["code"] for p in (await apply_assessments_async(s, [art.id]))[art.id].reasons["priority"]
    ]
    assert "kev" not in codes

    s.add(CveTracker(cve_id="CVE-2026-0002", client_id="p6-b", cisa_kev=True))
    await s.flush()

    a = (await apply_assessments_async(s, [art.id]))[art.id]
    assert {"code": "kev", "points": 15} in a.reasons["priority"]


@pytest.mark.asyncio
async def test_case_variant_rows_prefer_analyst(async_db_session: AsyncSession) -> None:
    s = async_db_session
    s.add(_sr("unit42", "B", "vendor_research", origin="default"))
    await s.flush()
    s.add(_sr("Unit42", "A", "vendor_research", origin="analyst"))
    art = _article("https://ex.com/u42", "UNIT42")
    s.add(art)
    await s.flush()

    a = (await apply_assessments_async(s, [art.id]))[art.id]

    assert a.reliability_grade == "A"
    assert (await _cols(s, art.id))[0] == "A"


@pytest.mark.asyncio
async def test_overrides_respected(async_db_session: AsyncSession) -> None:
    s = async_db_session
    s.add(_sr("Hackernews", "C", "news"))
    cred = _article("https://ex.com/ov1", "Hackernews", overrides={"credibility": 5})
    conf = _article("https://ex.com/ov2", "Hackernews", overrides={"confidence_score": 88})
    s.add_all([cred, conf])
    await s.flush()

    result = await apply_assessments_async(s, [cred.id, conf.id])

    assert result[cred.id].credibility == 5
    assert result[conf.id].confidence_score == 88
    assert (await _cols(s, cred.id))[1] == 5
    assert (await _cols(s, conf.id))[2] == 88


def _seed_rich(suffix: str) -> tuple[Article, list[Any]]:
    # URL beda per sesi: dua transaksi terbuka dengan `url_hash` sama saling mengunci.
    art = _article(
        f"https://ex.com/rich-{suffix}",
        "Unit42",
        confirmed_incident=True,
        overrides={"confidence_score": 77},
    )
    return art, [_sr("Unit42", "B", "vendor_research"), art]


def _children(art: Article) -> list[Any]:
    return [
        ArticleTTP(article_id=art.id, ttp_id="T1059", ttp_name="x", source="explicit"),
        ArticleTTP(article_id=art.id, ttp_id="T1566", ttp_name="y", source="llm"),
        ArticleTTP(article_id=art.id, ttp_id="T1078", ttp_name="z", source="keyword"),
        ArticleThreatActor(article_id=art.id, threat_actor="APT41"),
    ]


@pytest.mark.asyncio
async def test_sync_and_async_agree(db_session: Session, async_db_session: AsyncSession) -> None:
    art_s, objs_s = _seed_rich("sync")
    db_session.add_all(objs_s)
    db_session.flush()
    db_session.add_all(_children(art_s))
    db_session.flush()
    sync_result = apply_assessments(db_session, [art_s.id])

    art_a, objs_a = _seed_rich("async")
    async_db_session.add_all(objs_a)
    await async_db_session.flush()
    async_db_session.add_all(_children(art_a))
    await async_db_session.flush()
    async_result = await apply_assessments_async(async_db_session, [art_a.id])

    assert sync_result[art_s.id] == async_result[art_a.id]
    assert _cols_sync(db_session, art_s.id) == await _cols(async_db_session, art_a.id)
    # B (vendor_research, primer) + TTP eksplisit -> 2; prioritas = 77 + 25 + 6 + 8.
    assert async_result[art_a.id].admiralty_code == "B2"
    assert async_result[art_a.id].priority_score == 77 + 25 + 6 + 8


@pytest.mark.asyncio
async def test_malformed_override_is_ignored_not_fatal(async_db_session: AsyncSession) -> None:
    # Satu nilai `overrides` JSONB yang rusak tidak boleh menggagalkan batch 500 artikel: nilai
    # bukan int (termasuk bool) atau di luar rentang dianggap tidak ada override.
    s = async_db_session
    s.add(_sr("Hackernews", "C", "news"))
    bad = _article(
        "https://ex.com/ov-bad",
        "Hackernews",
        overrides={"credibility": "high", "confidence_score": True},
    )
    # di luar rentang: credibility 0/7 melanggar ck_articles_credibility_range
    high = _article(
        "https://ex.com/ov-high",
        "Hackernews",
        overrides={"credibility": 7, "confidence_score": 101},
    )
    low = _article(
        "https://ex.com/ov-low", "Hackernews", overrides={"credibility": 0, "confidence_score": -1}
    )
    good = _article("https://ex.com/ov-good", "Hackernews", overrides={"credibility": 2})
    s.add_all([bad, high, low, good])
    await s.flush()

    result = await apply_assessments_async(s, [bad.id, high.id, low.id, good.id])
    await s.flush()

    for art in (bad, high, low):
        assert result[art.id].admiralty_code == "C4"
        assert result[art.id].confidence_score == 40
    assert result[good.id].credibility == 2
