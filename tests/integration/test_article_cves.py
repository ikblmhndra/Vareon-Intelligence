"""`article_cves` menggantikan IOC bertipe `cve` -- Postgres REAL (testcontainers)."""

from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType

import pytest
from cti_api.services import campaign as campaign_service
from cti_core.db.models.article_cve import ArticleCve
from cti_core.db.models.ioc import IOC
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.article_cve import AsyncArticleCveRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_enrich.routing import RoutingResult
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.persist import persist
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from tests.integration.test_campaign_service import _TODAY, _seed_campaign_articles

_VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _persist(session: Session, title: str) -> None:
    persist(
        session=session,
        url="https://news.example/article-cves",
        title=title,
        source="s",
        scraper_id=None,
        posted_on=None,
        classify_result=ClassifyResult(related_cyber=True, confidence=0.9),
        score_result=None,
        routing_result=RoutingResult(news_type="General", alert_topics=[], msg_data=""),
        ttp_result=None,
        ioc_data={"cves": ["cve-2026-1234"]},
        c2_indicator=False,
    )


def test_persist_writes_article_cves_not_iocs(db_session: Session) -> None:
    _persist(db_session, "Patch CVE-2026-1234 now")
    _persist(db_session, "Patch CVE-2026-1234 now")  # replay: tidak menambah baris

    rows = db_session.execute(select(ArticleCve)).scalars().all()
    assert [(r.cve_id, r.in_title) for r in rows] == [("CVE-2026-1234", True)]
    assert db_session.execute(select(IOC).where(IOC.type == "cve")).first() is None


@pytest.mark.asyncio
async def test_cve_ids_by_article_reads_new_table(async_db_session: AsyncSession) -> None:
    articles = AsyncArticleRepo(async_db_session)
    first = await articles.upsert(url="https://example.com/a", title="A", source="s")
    second = await articles.upsert(url="https://example.com/b", title="B", source="s")
    third = await articles.upsert(url="https://example.com/c", title="C", source="s")
    repo = AsyncArticleCveRepo(async_db_session)
    await repo.add_many(first.id, ["CVE-2026-1111", "cve-2026-2222"], "A")
    await repo.add_many(second.id, ["CVE-2026-1111"], "B")

    found = await repo.cve_ids_by_article([first.id, second.id, third.id])

    assert found == {first.id: {"CVE-2026-1111", "CVE-2026-2222"}, second.id: {"CVE-2026-1111"}}
    assert await repo.cve_ids_by_article([]) == {}


@pytest.mark.asyncio
async def test_campaign_cve_ids_from_article_cves(async_db_session: AsyncSession) -> None:
    await AsyncClientRepo(async_db_session).ensure_default()
    article_ids = await _seed_campaign_articles(async_db_session)
    repo = AsyncArticleCveRepo(async_db_session)
    await repo.add_many(article_ids[0], ["CVE-2026-9001"], "t")
    await repo.add_many(article_ids[1], ["CVE-2026-9002"], "t")

    campaigns = await campaign_service.get_recent_campaigns(
        async_db_session, days=7, client_id="default", min_size=2
    )

    assert len(campaigns) == 1
    assert sorted(campaigns[0]["cve_ids"]) == ["CVE-2026-9001", "CVE-2026-9002"]
    assert _TODAY  # seed memakai tanggal yang sama dengan test campaign


def _load_migration() -> ModuleType:
    path = next(_VERSIONS.glob("d1a5c8e3f2b7_*.py"))
    spec = importlib.util.spec_from_file_location("article_cves_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_migration_moves_cve_iocs(async_db_session: AsyncSession) -> None:
    migration = _load_migration()
    articles = AsyncArticleRepo(async_db_session)
    first = await articles.upsert(
        url="https://example.com/m1", title="Bug cve-2026-5555", source="s"
    )
    second = await articles.upsert(url="https://example.com/m2", title="Other", source="s")
    iocs = AsyncIOCRepo(async_db_session)
    for article in (first, second, first):  # tautan kedua ke artikel pertama = duplikat
        await iocs.upsert(
            type="cve",
            value="CVE-2026-5555",
            source_url="u",
            source_name="s",
            article_id=article.id,
        )
    await iocs.upsert(type="ip", value="203.0.113.9", source_url="u", source_name="s")

    await async_db_session.execute(text(migration.COPY_CVE_SQL))
    await async_db_session.execute(text(migration.DELETE_CVE_IOCS_SQL))

    rows = (await async_db_session.execute(select(ArticleCve))).scalars().all()
    assert {(r.article_id, r.cve_id, r.in_title) for r in rows} == {
        (first.id, "CVE-2026-5555", True),
        (second.id, "CVE-2026-5555", False),
    }
    remaining = (await async_db_session.execute(select(IOC.type, IOC.value))).all()
    assert remaining == [("ip", "203.0.113.9")]
