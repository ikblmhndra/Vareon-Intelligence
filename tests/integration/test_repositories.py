"""Integrasi repository lawan Postgres beneran (testcontainers), skema
lewat `alembic upgrade head` sungguhan -- bukan `create_all()`."""

from __future__ import annotations

import pytest
from cti_core.db.repositories.article import ArticleRepo, AsyncArticleRepo
from cti_core.db.repositories.indicator import IndicatorRepo
from cti_core.db.repositories.scraper import ScraperRunRepo
from cti_core.urlkit import url_hash
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


def test_article_upsert_creates_then_updates(db_session: Session) -> None:
    repo = ArticleRepo(db_session)

    a1 = repo.upsert(url="https://example.com/x", title="Judul awal", source="Test")
    assert a1.seen_count == 1
    assert a1.url_hash == url_hash("https://example.com/x")

    # scrape ulang URL yang SAMA -- versi Mongo lama ($setOnInsert-only)
    # gak pernah update field ini; di sini HARUS update.
    a2 = repo.upsert(url="https://example.com/x", title="Judul diperbaiki", source="Test")
    assert a2.id == a1.id
    assert a2.title == "Judul diperbaiki"
    assert a2.seen_count == 2


def test_article_upsert_never_touches_overrides(db_session: Session) -> None:
    repo = ArticleRepo(db_session)
    article = repo.upsert(url="https://example.com/y", title="Asli", source="Test")

    repo.set_overrides(article, confidence_score=95, news_type="analyst_corrected")

    # scraper re-scrape -- overrides analis HARUS bertahan
    updated = repo.upsert(
        url="https://example.com/y", title="Asli v2", source="Test", confidence_score=10
    )
    assert updated.confidence_score == 10  # kolom mesin ke-timpa
    merged = repo.to_dict(updated)
    assert merged["confidence_score"] == 95  # tapi overrides yang menang
    assert merged["news_type"] == "analyst_corrected"


def test_article_upsert_rejects_identity_field_as_machine_field(db_session: Session) -> None:
    repo = ArticleRepo(db_session)
    with pytest.raises(ValueError, match="identitas"):
        repo.upsert(url="https://example.com/z", title="x", source="Test", url_hash="hacked")


def test_article_upsert_rejects_unknown_field(db_session: Session) -> None:
    repo = ArticleRepo(db_session)
    with pytest.raises(ValueError, match="bukan kolom"):
        repo.upsert(url="https://example.com/w", title="x", source="Test", this_typo_field=1)


def test_ioc_upsert_accumulates_sources_and_seen_count(db_session: Session) -> None:
    repo = IndicatorRepo(db_session)

    ioc = repo.upsert(
        type="domain", value="evil.example", source_url="https://a.com/1", source_name="A"
    )
    assert ioc.seen_count == 1
    assert len(ioc.sources) == 1

    ioc2 = repo.upsert(
        type="domain", value="evil.example", source_url="https://b.com/2", source_name="B"
    )
    assert ioc2.id == ioc.id
    assert ioc2.seen_count == 2
    assert len(ioc2.sources) == 2


def test_ioc_feedback_updates_tp_fp_counts(db_session: Session) -> None:
    repo = IndicatorRepo(db_session)
    ioc = repo.upsert(type="ip", value="1.2.3.4", source_url="https://a.com", source_name="A")

    repo.add_feedback(ioc, verdict="tp", submitted_by="analyst1")
    repo.add_feedback(ioc, verdict="fp", submitted_by="analyst2", note="allowlisted CDN")

    assert ioc.tp_count == 1
    assert ioc.fp_count == 1
    assert len(ioc.feedback) == 2


def test_scraper_run_lifecycle_distinguishes_empty_from_crash(db_session: Session) -> None:
    """Ini KEMAMPUAN yang gak ada di sistem lama -- scraper_runs lama cuma
    kebentuk kalau ada artikel diterima, jadi nol-item vs crash gak
    kebedain (lihat plan §8.1)."""
    repo = ScraperRunRepo(db_session)

    empty_run = repo.start(run_id="run-empty-1", scraper_id="gbhackers", trigger="beat")
    repo.finish(empty_run, status="empty", items_found=0)
    assert empty_run.status == "empty"
    assert empty_run.finished_at is not None
    assert empty_run.duration_ms is not None and empty_run.duration_ms >= 0

    crash_run = repo.start(run_id="run-crash-1", scraper_id="gbhackers", trigger="beat")
    repo.finish(
        crash_run,
        status="parse_error",
        items_found=0,
        errors=[{"stage": "parse", "message": "XPath matched nothing"}],
    )
    assert crash_run.status == "parse_error"
    assert crash_run.errors[0]["message"] == "XPath matched nothing"

    # dua run beda scraper_id yang sama, status beda -- kebedain lewat query
    fetched = repo.get_by_run_id("run-crash-1")
    assert fetched is not None
    assert fetched.status == "parse_error"


def test_scraper_run_rejects_unknown_status(db_session: Session) -> None:
    repo = ScraperRunRepo(db_session)
    run = repo.start(run_id="run-bad-status", scraper_id="x")
    with pytest.raises(ValueError, match="status terminal"):
        repo.finish(run, status="not_a_real_status")


async def test_async_article_repo_upsert_works(async_db_session: AsyncSession) -> None:
    """Jalur async (dipakai FastAPI, Fase 7) -- bukan cuma diasumsikan sama
    kayak sync karena kodenya keliatan mirip."""
    repo = AsyncArticleRepo(async_db_session)

    a1 = await repo.upsert(url="https://example.com/async-1", title="Async 1", source="Test")
    assert a1.seen_count == 1

    a2 = await repo.upsert(url="https://example.com/async-1", title="Async 1 v2", source="Test")
    assert a2.id == a1.id
    assert a2.seen_count == 2

    fetched = await repo.get_by_url("https://example.com/async-1")
    assert fetched is not None
    assert fetched.title == "Async 1 v2"


def test_set_enrichment_dedups_ttps_by_id_even_when_names_differ(db_session: Session) -> None:
    """Regresi e2e staging Fase 10: LLM ngembaliin "T1176" dua kali dgn nama
    beda. Dedup per tuple (id, nama) meloloskan keduanya -> UniqueViolation
    `uq_article_ttp` -> seluruh artikel hilang (rollback)."""
    repo = ArticleRepo(db_session)
    article = repo.upsert(url="https://example.com/ttp-dup", title="TTP kembar", source="Test")

    repo.set_enrichment(
        article,
        ttps=[
            ("T1176", "Browser Extensions"),
            ("T1059.001", "PowerShell"),
            ("T1176", "Software Extensions"),
        ],
    )
    db_session.flush()  # kalau dedup salah, IntegrityError meledak di sini

    kept = {t.ttp_id: t.ttp_name for t in article.ttps}
    assert kept == {"T1176": "Browser Extensions", "T1059.001": "PowerShell"}  # nama pertama menang


async def test_async_set_enrichment_dedups_ttps_by_id_even_when_names_differ(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    article = await repo.upsert(url="https://example.com/ttp-dup-async", title="t", source="Test")

    await repo.set_enrichment(article, ttps=[("T1176", "A"), ("T1176", "B")])
    await async_db_session.flush()

    assert [(t.ttp_id, t.ttp_name) for t in article.ttps] == [("T1176", "A")]


# --- set_enrichment idempoten (Fase 10.E) ------------------------------------------
#
# Persist ulang artikel yang SAMA -- dua scraper meliput URL yang sama (dedup itu
# per-scraper), atau retry sesudah persist -- dulu gagal `UniqueViolation`:
# SQLAlchemy INSERT baris baru berkunci sama SEBELUM DELETE baris lama.

ENRICHMENT = {
    "countries": [("ID", "victim"), ("US", "actor")],
    "industries": ["General"],
    "threat_actors": ["Apt41"],
    "ttps": [("T1059", "Command and Scripting Interpreter")],
}


def _snapshot(article) -> dict:
    return {
        "countries": sorted((c.country_code, c.role) for c in article.countries),
        "industries": sorted(i.industry for i in article.industries),
        "threat_actors": sorted(t.threat_actor for t in article.threat_actors),
        "ttps": sorted((t.ttp_id, t.ttp_name) for t in article.ttps),
    }


def test_set_enrichment_twice_with_the_same_values_is_a_noop_not_a_unique_violation(
    db_session: Session,
) -> None:
    repo = ArticleRepo(db_session)
    article = repo.upsert(url="https://example.com/dup", title="t", source="s")
    repo.set_enrichment(article, **ENRICHMENT)
    ids_before = sorted(i.id for i in article.industries) + sorted(c.id for c in article.countries)

    repo.set_enrichment(article, **ENRICHMENT)  # dulu: UniqueViolation uq_article_industry

    assert (
        sorted(i.id for i in article.industries) + sorted(c.id for c in article.countries)
        == ids_before
    )
    assert _snapshot(article)["industries"] == ["General"]


def test_set_enrichment_applies_added_removed_and_renamed_children(db_session: Session) -> None:
    repo = ArticleRepo(db_session)
    article = repo.upsert(url="https://example.com/chg", title="t", source="s")
    repo.set_enrichment(article, **ENRICHMENT)

    repo.set_enrichment(
        article,
        countries=[("ID", "victim"), ("ID", "mentioned")],  # US/actor hilang, ID/mentioned baru
        industries=["General", "Finance & Insurance"],
        threat_actors=["Lazarus"],  # Apt41 diganti
        ttps=[("T1059", "Renamed Technique"), ("T1566", "Phishing")],
    )
    db_session.flush()
    db_session.expire_all()

    assert _snapshot(article) == {
        "countries": [("ID", "mentioned"), ("ID", "victim")],
        "industries": ["Finance & Insurance", "General"],
        "threat_actors": ["Lazarus"],
        "ttps": [("T1059", "Renamed Technique"), ("T1566", "Phishing")],
    }


def test_set_enrichment_can_clear_everything(db_session: Session) -> None:
    repo = ArticleRepo(db_session)
    article = repo.upsert(url="https://example.com/clr", title="t", source="s")
    repo.set_enrichment(article, **ENRICHMENT)

    repo.set_enrichment(article)
    db_session.expire_all()

    assert _snapshot(article) == {
        "countries": [], "industries": [], "threat_actors": [], "ttps": [],
    }  # fmt: skip


@pytest.mark.asyncio
async def test_async_set_enrichment_twice_with_the_same_values_is_a_noop(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    article = await repo.upsert(url="https://example.com/adup", title="t", source="s")
    await repo.set_enrichment(article, **ENRICHMENT)

    await repo.set_enrichment(article, **ENRICHMENT)

    assert _snapshot(article)["industries"] == ["General"]
