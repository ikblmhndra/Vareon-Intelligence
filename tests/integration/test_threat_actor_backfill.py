"""Threat actor & Risk Matrix kosong di staging -- QA 2026-10-01 (BUG-B2/D1/D4).

Reproduksi kondisi staging di Postgres beneran:
- artikel yang tersimpan SEBELUM fix: tanpa `article_threat_actors`, negara
  cuma role `victim` (persist lama gak pernah nulis `mentioned` untuk negara
  GPT) -> dropdown TA kosong, PIR "Monitor ShinyHunters" 0 match, Risk Matrix
  0 sel;
- `python -m cti_enrich.backfill` (setelah `threat_actor_groups` di-seed)
  harus membetulkan ketiganya, tanpa LLM dan tanpa alert;
- artikel BARU lewat `run_pipeline` (score + routing + persist asli) langsung
  benar.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import pytest
from cti_api.services import risk_matrix
from cti_core.db.models.article import Article
from cti_core.db.models.threat_reference import ThreatActorGroup
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from cti_enrich import pipeline
from cti_enrich.backfill import BackfillError, backfill_articles
from cti_enrich.stages.classify import ClassifyResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_TODAY = datetime.date.today()
_INDUSTRY = "Finance & Insurance"
_GROUPS = ["shinyhunters", "star blizzard", "temp.periscope"]


async def _seed_pre_fix_corpus(session: AsyncSession) -> None:
    """Bentuk data persis yang ditulis pipeline lama di staging."""
    session.add_all(ThreatActorGroup(name=g, source="malpedia") for g in _GROUPS)
    repo = AsyncArticleRepo(session)
    rows = [
        ("a1", "FBI tells ShinyHunters members to turn themselves in", "Incident"),
        ("a2", "ShinyHunters claims breach of another SaaS tenant", "Data Breach Article"),
        ("a3", "Russia's Star Blizzard Ditches ClickFix for new lure", "global"),
        (
            "a4",
            "ShinyHunters-proof your SSO: best practices",
            "Security Technology & Best Practices",
        ),
    ]
    for slug, title, news_type in rows:
        article = await repo.upsert(
            url=f"https://example.com/{slug}",
            title=title,
            source="Test",
            posted_on=_TODAY,
            news_type=news_type,
        )
        await repo.set_enrichment(article, industries=[_INDUSTRY], countries=[("US", "victim")])
    await session.flush()


async def _backfill(session: AsyncSession, **kwargs: object):
    return await session.run_sync(lambda s: backfill_articles(s, batch_size=2, **kwargs))


@pytest.mark.asyncio
async def test_backfill_fixes_options_pir_coverage_and_risk_matrix(
    async_db_session: AsyncSession,
) -> None:
    session = async_db_session
    await _seed_pre_fix_corpus(session)
    article_repo = AsyncArticleRepo(session)
    pir_repo = AsyncPIRRepo(session)
    criteria = {"threat_actors": ["Shinyhunters"]}  # kriteria PIR staging apa adanya

    # --- kondisi staging (bug) ---
    assert (await article_repo.get_filter_options())["threat_actors"] == []
    assert (await pir_repo.compute_coverage(article_repo, criteria, None, None))[0] == 0
    # Risk Matrix udah baca negara role apa pun (fix filter negara), jadi sel US
    # udah ada sebelum backfill -- yang kosong cuma top actor-nya.
    risk_matrix._CACHE.clear()
    before = (await risk_matrix.get_risk_matrix(session))["matrix"]
    assert [(c["industry"], c["country"]) for c in before] == [(_INDUSTRY, "US")]
    assert not before[0]["top_actors"]

    stats = await _backfill(session)

    assert stats.scanned == 4
    assert stats.articles_with_new_actors == 3  # a4 (best practice) gak pernah di-score
    assert stats.actor_rows_added == 3
    assert stats.mentioned_rows_added == 4

    options = await article_repo.get_filter_options()
    assert options["threat_actors"] == ["Shinyhunters", "Star blizzard"]
    assert options["countries"] == ["US"]

    total, last_match, recent = await pir_repo.compute_coverage(article_repo, criteria, None, None)
    assert (total, recent) == (2, 2)
    assert last_match == _TODAY.isoformat()

    risk_matrix._CACHE.clear()
    matrix = (await risk_matrix.get_risk_matrix(session))["matrix"]
    assert [(c["industry"], c["country"], c["current_count"]) for c in matrix] == [
        (_INDUSTRY, "US", 4)
    ]
    assert matrix[0]["top_actors"][0] == "Shinyhunters"
    risk_matrix._CACHE.clear()


@pytest.mark.asyncio
async def test_backfill_is_idempotent_and_only_adds(async_db_session: AsyncSession) -> None:
    session = async_db_session
    await _seed_pre_fix_corpus(session)
    repo = AsyncArticleRepo(session)
    a1 = await repo.get_by_url("https://example.com/a1")
    assert a1 is not None
    # TA yang sudah ada (beda kapital) gak boleh diduplikasi, yang lain gak dihapus
    await repo.set_enrichment(
        a1,
        industries=[_INDUSTRY],
        countries=[("US", "victim")],
        threat_actors=["SHINYHUNTERS", "Other actor"],
    )
    await session.flush()

    await _backfill(session)
    second = await _backfill(session)

    assert (second.actor_rows_added, second.mentioned_rows_added) == (0, 0)
    session.expire_all()
    a1 = await repo.get_by_url("https://example.com/a1")
    assert a1 is not None
    assert sorted(t.threat_actor for t in a1.threat_actors) == ["Other actor", "SHINYHUNTERS"]
    assert sorted((c.country_code, c.role) for c in a1.countries) == [
        ("US", "mentioned"),
        ("US", "victim"),
    ]


@pytest.mark.asyncio
async def test_backfill_since_limits_scope(async_db_session: AsyncSession) -> None:
    await _seed_pre_fix_corpus(async_db_session)
    stats = await _backfill(async_db_session, since=_TODAY + datetime.timedelta(days=1))
    assert stats.scanned == 0


def test_backfill_refuses_to_run_without_seeded_groups(db_session: Session) -> None:
    with pytest.raises(BackfillError, match="threat_actor_groups"):
        backfill_articles(db_session)


# --- artikel baru lewat pipeline asli ------------------------------------------------


@pytest.fixture
def pipeline_session(_migrated_schema: None) -> Iterator[Session]:
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


def test_new_article_gets_threat_actor_and_mentioned_country(
    pipeline_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`score` + `route` + `persist` ASLI; cuma stage LLM/jaringan yang di-stub."""
    monkeypatch.setattr(
        pipeline,
        "classify",
        lambda title: ClassifyResult(
            related_cyber=True,
            confidence=0.9,
            industries_impacted=[_INDUSTRY],
            victim_countries=["United States"],
        ),
    )
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: "")
    monkeypatch.setattr(pipeline, "summarize", lambda text: "")  # body kosong -> tanpa NER
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(
        pipeline, "extract_ttps", lambda s: pipeline.TtpResult(has_techniques=False)
    )
    alerts: list[object] = []
    monkeypatch.setattr(pipeline, "route_alerts", alerts.append)
    pipeline_session.add_all(ThreatActorGroup(name=g, source="malpedia") for g in _GROUPS)
    pipeline_session.flush()

    outcome = pipeline.run_pipeline(
        # P4 (Tier 1): nama TA satu kata dari `threat_actor_groups` butuh kata konteks di dekatnya
        # ("hackers"); tanpa itu "ShinyHunters" tidak dicocokkan lagi.
        title="FBI tells ShinyHunters hackers to turn themselves in",
        url="https://example.com/new",
        posted_on=_TODAY,
        source="Test",
        scraper_id="t",
        session=pipeline_session,
    )

    article = pipeline_session.scalar(select(Article).where(Article.id == outcome.article_id))
    assert article is not None
    assert [t.threat_actor for t in article.threat_actors] == ["Shinyhunters"]
    assert sorted((c.country_code, c.role) for c in article.countries) == [
        ("US", "mentioned"),
        ("US", "victim"),
    ]
    assert len(alerts) == 1
