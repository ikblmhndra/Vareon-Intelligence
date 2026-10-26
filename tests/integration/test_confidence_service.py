"""Integration test `cti_api.services.confidence` -- Postgres REAL
(testcontainers). Fase 7.4 Grup D."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Any

import pytest
from cti_api.services import confidence as svc
from cti_core.db.models.article import Article
from cti_core.db.models.story import Story
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.source_reliability import AsyncSourceReliabilityRepo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _columns(session: AsyncSession, article_id: int) -> tuple[Any, ...]:
    # Baca kolom langsung (bukan objek di identity map): `apply_assessments_async` menulis lewat
    # bulk UPDATE yang tidak menyegarkan objek `Article` yang sudah dimuat sesi.
    row = (
        await session.execute(
            select(
                Article.reliability_grade,
                Article.credibility,
                Article.confidence_score,
                Article.priority_score,
            ).where(Article.id == article_id)
        )
    ).one()
    return tuple(row)


async def test_compute_article_confidence_uses_source_rating(
    async_db_session: AsyncSession,
) -> None:
    sr_repo = AsyncSourceReliabilityRepo(async_db_session)
    await sr_repo.add_entry(
        source_name="GBHackers",
        analyst_name="analyst1",
        reliability_grade="A",
        credibility_code="1",
        notes="",
    )
    article_repo = AsyncArticleRepo(async_db_session)
    article = await article_repo.upsert(
        url="https://example.com/a1", title="Apt41 breach", source="GBHackers"
    )
    await article_repo.set_enrichment(
        article,
        threat_actors=["Apt41"],
        ttps=[("T1059", "Command Scripting"), ("T1574", "Hijack")],
    )

    result = await svc.compute_article_confidence(async_db_session, article)
    # P6: kredibilitas per artikel, bukan kode sumber. Sumber A tanpa content_kind, satu sumber,
    # TTP llm (bukan eksplisit) -> A4; confidence (90+30)/2 = 60; prioritas 60 + 2*3 TTP + 8 aktor.
    assert result.admiralty_code == "A4"
    assert result.confidence_score == 60
    assert result.priority_score == 74
    # hanya menghitung, tidak menulis
    assert (await _columns(async_db_session, article.id))[1] is None


async def test_compute_article_confidence_source_case_insensitive(
    async_db_session: AsyncSession,
) -> None:
    sr_repo = AsyncSourceReliabilityRepo(async_db_session)
    await sr_repo.add_entry(
        source_name="BleepingComputer",
        analyst_name="analyst1",
        reliability_grade="B",
        credibility_code="2",
        notes="",
    )
    article_repo = AsyncArticleRepo(async_db_session)
    article = await article_repo.upsert(
        url="https://example.com/a2", title="Some article", source="bleepingcomputer"
    )

    result = await svc.compute_article_confidence(async_db_session, article)
    # B4: (70+30)/2 = 50
    assert result.admiralty_code == "B4"
    assert result.confidence_score == 50


async def test_compute_article_confidence_no_rating_is_f6(
    async_db_session: AsyncSession,
) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    article = await article_repo.upsert(
        url="https://example.com/a3", title="Unknown source article", source="TotallyUnknownBlog"
    )
    result = await svc.compute_article_confidence(async_db_session, article)
    assert result.admiralty_code == "F6"
    assert result.confidence_score == 50


async def test_compute_and_store_article_confidence_writes_columns(
    async_db_session: AsyncSession,
) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    article = await article_repo.upsert(
        url="https://example.com/a4", title="Article to score", source="X"
    )

    result = await svc.compute_and_store_article_confidence(async_db_session, article.id)
    assert result is not None
    assert (result.admiralty_code, result.confidence_score, result.priority_score) == (
        "F6",
        50,
        50,
    )
    assert await _columns(async_db_session, article.id) == ("F", 6, 50, 50)
    # kolom mesin yang ditulis; `overrides` (koreksi analis) tidak disentuh
    overrides = await async_db_session.scalar(
        select(Article.overrides).where(Article.id == article.id)
    )
    assert overrides == {}


async def test_compute_and_store_respects_confidence_override(
    async_db_session: AsyncSession,
) -> None:
    # P6 spec 4.5: override analis tidak lagi melewati artikel; `assess` memakainya, jadi kolom
    # `confidence_score` = nilai override dan kredibilitas/prioritas tetap dihitung.
    article_repo = AsyncArticleRepo(async_db_session)
    article = await article_repo.upsert(url="https://example.com/a5", title="Pinned", source="X")
    await article_repo.set_overrides(article, confidence_score=7)

    result = await svc.compute_and_store_article_confidence(async_db_session, article.id)
    assert result is not None
    assert await _columns(async_db_session, article.id) == ("F", 6, 7, 7)


async def test_compute_and_store_article_confidence_missing_returns_none(
    async_db_session: AsyncSession,
) -> None:
    assert await svc.compute_and_store_article_confidence(async_db_session, 999999) is None


async def test_recompute_all_confidence_updates_every_article(
    async_db_session: AsyncSession,
) -> None:
    sr_repo = AsyncSourceReliabilityRepo(async_db_session)
    await sr_repo.add_entry(
        source_name="GBHackers",
        analyst_name="analyst1",
        reliability_grade="A",
        credibility_code="1",
        notes="",
    )
    article_repo = AsyncArticleRepo(async_db_session)
    a1 = await article_repo.upsert(url="https://example.com/r1", title="A1", source="GBHackers")
    a2 = await article_repo.upsert(url="https://example.com/r2", title="A2", source="Unrated")

    result = await svc.recompute_all_confidence(async_db_session, batch_size=1)
    assert result["updated"] >= 2

    assert await _columns(async_db_session, a1.id) == ("A", 4, 60, 60)
    assert await _columns(async_db_session, a2.id) == ("F", 6, 50, 50)


async def test_recompute_all_confidence_restricted_to_story_members(
    async_db_session: AsyncSession,
) -> None:
    # `story_ids` (dipakai task `confidence.refresh_stories`) hanya menilai ulang anggota story.
    s = async_db_session
    now = datetime.datetime.now(datetime.UTC)
    story = Story(title="t", lead_source="x", first_seen_at=now, last_seen_at=now)
    other = Story(title="u", lead_source="y", first_seen_at=now, last_seen_at=now)
    s.add_all([story, other])
    await s.flush()
    article_repo = AsyncArticleRepo(s)
    member = await article_repo.upsert(
        url="https://example.com/st1", title="M", source="S", story_id=story.id
    )
    outsider = await article_repo.upsert(
        url="https://example.com/st2", title="O", source="S", story_id=other.id
    )
    loose = await article_repo.upsert(url="https://example.com/st3", title="L", source="S")

    result = await svc.recompute_all_confidence(s, story_ids=[story.id])

    assert result == {"updated": 1}
    assert (await _columns(s, member.id))[1] == 6
    assert (await _columns(s, outsider.id))[1] is None
    assert (await _columns(s, loose.id))[1] is None


async def test_recompute_all_confidence_caps_batch_at_500(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Loader fakta dirancang untuk maks 500 id per panggilan; batch lebih besar dipotong.
    article_repo = AsyncArticleRepo(async_db_session)
    await article_repo.upsert(url="https://example.com/cap", title="Cap", source="S")
    sizes: list[int] = []
    real = svc.apply_assessments_async

    async def spy(session: AsyncSession, ids: Sequence[int]) -> dict[int, Any]:
        sizes.append(len(ids))
        return await real(session, ids)

    monkeypatch.setattr(svc, "apply_assessments_async", spy)
    await svc.recompute_all_confidence(async_db_session, batch_size=10_000)
    assert sizes and max(sizes) <= 500


async def test_recompute_all_confidence_commits_each_batch(api_session: AsyncSession) -> None:
    # Recompute penuh di tabel besar tidak boleh memegang lock baris sepanjang run: tiap batch
    # di-commit sendiri bila `commit_each_batch=True` (dipakai task worker).
    article_repo = AsyncArticleRepo(api_session)
    for i in range(3):
        await article_repo.upsert(url=f"https://example.com/cb{i}", title=f"C{i}", source="S")
    commits = 0
    real_commit = api_session.commit

    async def counting_commit() -> None:
        nonlocal commits
        commits += 1
        await real_commit()

    api_session.commit = counting_commit  # type: ignore[method-assign]
    result = await svc.recompute_all_confidence(api_session, batch_size=1, commit_each_batch=True)
    assert result["updated"] >= 3
    assert commits >= 3


async def test_recompute_ignores_keyword_ttps_like_persist(
    async_db_session: AsyncSession,
) -> None:
    # Spec P4: bonus TTP hanya explicit + llm. Persist dan recompute (per artikel maupun massal)
    # memakai loader fakta yang sama: prioritas = 50 + 1 TTP llm * 3, keyword tidak dihitung.
    from cti_core.attack_ttp import NormalizedTTP

    article_repo = AsyncArticleRepo(async_db_session)
    created = await article_repo.upsert(
        url="https://example.com/kw1", title="Keyword TTP article", source="UnratedKw"
    )
    article = await article_repo.get_by_id(created.id)
    assert article is not None
    await article_repo.set_enrichment(
        article,
        ttps=[
            NormalizedTTP("T1059", "Command and Scripting Interpreter", source="llm"),
            NormalizedTTP("T1566", "Phishing", source="keyword"),
        ],
    )
    assert sorted(t.source for t in article.ttps) == ["keyword", "llm"]

    assert (await svc.compute_article_confidence(async_db_session, article)).priority_score == 53
    await svc.recompute_all_confidence(async_db_session, source_name="UnratedKw")
    assert (await _columns(async_db_session, created.id))[3] == 53


async def test_recompute_ioc_confidence_and_actionability_persists_all_fields(
    async_db_session: AsyncSession,
) -> None:
    ioc_repo = AsyncIOCRepo(async_db_session)
    created = await ioc_repo.upsert(
        type="sha256",
        value="a" * 64,
        source_url="https://a.com",
        source_name="a",
    )
    # re-fetch dulu: `.feedback` belum "loaded" abis cabang INSERT baru `upsert()` (objek
    # INSERT tidak lewat query `selectin`).
    ioc = await ioc_repo.get_by_id(created.id)
    assert ioc is not None
    await ioc_repo.add_feedback(ioc, verdict="tp", submitted_by="analyst1")

    now = datetime.datetime.now(datetime.UTC)
    updated = await svc.recompute_ioc_confidence_and_actionability(async_db_session, ioc, now=now)

    assert updated.confidence_score is not None
    assert updated.confidence_decayed_at == now
    assert updated.actionability_score is not None
    assert updated.actionability_label in {"block_now", "investigate", "monitor", "archive"}
    assert updated.recommended_action

    fetched = await ioc_repo.get_by_id(ioc.id)
    assert fetched is not None
    assert fetched.actionability_label == updated.actionability_label
