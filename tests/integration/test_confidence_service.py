"""Integration test `cti_api.services.confidence` -- Postgres REAL
(testcontainers). Fase 7.4 Grup D."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services import confidence as svc
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.source_reliability import AsyncSourceReliabilityRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


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

    score = await svc.compute_article_confidence(async_db_session, article)
    # rel=100, cred=100, base=100, ttp_bonus=min(2*5,20)=10, ta_bonus=min(1*10,10)=10 -> clamp 100
    assert score == 100


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
    created = await article_repo.upsert(
        url="https://example.com/a2", title="Some article", source="bleepingcomputer"
    )
    # re-fetch lewat `get_by_id()` (SELECT) -- objek langsung dari
    # `upsert()`'s cabang INSERT baru gak pernah lewat query `selectin`,
    # jadi `.ttps`/`.threat_actors` belum "loaded" (beda dari cabang
    # UPDATE yang emang query dulu). Sama pola persis kayak yang udah
    # didokumentasikan buat `CveTracker(...)`/`apply_exploit_hits` --
    # murni artefak test-setup, bukan bug produksi (router selalu manggil
    # `get_by_id()` dulu).
    article = await article_repo.get_by_id(created.id)
    assert article is not None

    score = await svc.compute_article_confidence(async_db_session, article)
    # rel=80, cred=80, base=80, no ttp/ta bonus
    assert score == 80


async def test_compute_article_confidence_no_rating_defaults_50(
    async_db_session: AsyncSession,
) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    created = await article_repo.upsert(
        url="https://example.com/a3", title="Unknown source article", source="TotallyUnknownBlog"
    )
    article = await article_repo.get_by_id(created.id)
    assert article is not None
    score = await svc.compute_article_confidence(async_db_session, article)
    assert score == 50


async def test_compute_and_store_article_confidence_writes_column(
    async_db_session: AsyncSession,
) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    article = await article_repo.upsert(
        url="https://example.com/a4", title="Article to score", source="X"
    )

    score = await svc.compute_and_store_article_confidence(async_db_session, article.id)
    assert score == 50

    fetched = await article_repo.get_by_id(article.id)
    assert fetched is not None
    # sejak 0.8.6 kolom mesin yang ditulis; `overrides` (koreksi analis) tidak disentuh
    assert fetched.confidence_score == 50
    assert "confidence_score" not in fetched.overrides
    merged = article_repo.to_dict(fetched)
    assert merged["confidence_score"] == 50


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
    assert result["updated"] == 2

    fetched1 = await article_repo.get_by_id(a1.id)
    fetched2 = await article_repo.get_by_id(a2.id)
    assert fetched1 is not None and fetched2 is not None
    assert article_repo.to_dict(fetched1)["confidence_score"] == 100
    assert article_repo.to_dict(fetched2)["confidence_score"] == 50


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
    # re-fetch dulu -- sama alasan kayak di `test_compute_article_confidence_*`
    # di atas, `.feedback` belum "loaded" abis cabang INSERT baru `upsert()`.
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
