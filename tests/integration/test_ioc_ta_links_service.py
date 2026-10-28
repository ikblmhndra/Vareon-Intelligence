"""Integration test `cti_api.services.ioc_ta_links.get_ioc_ta_links` --
Postgres REAL (testcontainers). Fase 7.4 Grup D -- `GET /api/iocs/
ta-links/{type}/{value}`, endpoint yang ketinggalan pas Fase 7.3
(blocker router `ta_groups`/`attack`, sekarang resolve Bagian 3)."""

from __future__ import annotations

import pytest
from cti_api.services import ioc_ta_links as svc
from cti_core.db.models.attack import AttackGroup
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from cti_core.db.repositories.ta import AsyncTARepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_returns_none_for_missing_ioc(async_db_session: AsyncSession) -> None:
    result = await svc.get_ioc_ta_links(async_db_session, "ip", "9.9.9.9")
    assert result is None


async def test_empty_threat_actors_when_no_links(async_db_session: AsyncSession) -> None:
    repo = AsyncIndicatorRepo(async_db_session)
    await repo.upsert(type="ip", value="1.2.3.4", source_url="https://a.com", source_name="a")
    result = await svc.get_ioc_ta_links(async_db_session, "ip", "1.2.3.4")
    assert result == {"threat_actors": []}


async def test_manual_tag_and_article_mention_combined(async_db_session: AsyncSession) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    article = await article_repo.upsert(
        url="https://example.com/a1", title="Apt41 breach", source="X"
    )
    await article_repo.set_enrichment(article, threat_actors=["Apt41", "Lazarus"])

    ioc_repo = AsyncIndicatorRepo(async_db_session)
    created = await ioc_repo.upsert(
        type="domain",
        value="evil.example",
        source_url="https://x.com",
        source_name="x",
        article_id=article.id,
    )
    ioc = await ioc_repo.get_by_id(created.id)
    assert ioc is not None
    await ioc_repo.add_threat_actors(ioc, ["Turla"])

    result = await svc.get_ioc_ta_links(async_db_session, "domain", "evil.example")
    assert result is not None
    names = {t["name"] for t in result["threat_actors"]}
    assert names == {"Apt41", "Lazarus", "Turla"}

    by_name = {t["name"]: t for t in result["threat_actors"]}
    assert by_name["Turla"]["source"] == "manual"
    assert by_name["Turla"]["article_count"] == 0
    assert by_name["Apt41"]["source"] == "article"
    assert by_name["Apt41"]["article_count"] == 1


async def test_manual_and_article_overlap_is_source_both(async_db_session: AsyncSession) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    article = await article_repo.upsert(
        url="https://example.com/a2", title="Apt41 again", source="X"
    )
    await article_repo.set_enrichment(article, threat_actors=["Apt41"])

    ioc_repo = AsyncIndicatorRepo(async_db_session)
    created = await ioc_repo.upsert(
        type="domain",
        value="both.example",
        source_url="https://x.com",
        source_name="x",
        article_id=article.id,
    )
    ioc = await ioc_repo.get_by_id(created.id)
    assert ioc is not None
    await ioc_repo.add_threat_actors(ioc, ["Apt41"])

    result = await svc.get_ioc_ta_links(async_db_session, "domain", "both.example")
    assert result is not None
    entry = result["threat_actors"][0]
    assert entry["name"] == "Apt41"
    assert entry["source"] == "both"


async def test_watchlist_is_unscoped_across_clients(async_db_session: AsyncSession) -> None:
    await AsyncClientRepo(async_db_session).create(client_id="client-a", name="A", countries=[])
    ta_repo = AsyncTARepo(async_db_session)
    await ta_repo.add_to_watchlist("Apt41", "client-a")

    article_repo = AsyncArticleRepo(async_db_session)
    article = await article_repo.upsert(url="https://example.com/a3", title="A3", source="X")
    await article_repo.set_enrichment(article, threat_actors=["Apt41"])

    ioc_repo = AsyncIndicatorRepo(async_db_session)
    await ioc_repo.upsert(
        type="domain",
        value="watched.example",
        source_url="https://x.com",
        source_name="x",
        article_id=article.id,
    )

    # cek dari perspektif client LAIN (client-b) -- watchlist tetap
    # kena karena ini UNSCOPED, port asimetri legacy apa adanya.
    result = await svc.get_ioc_ta_links(async_db_session, "domain", "watched.example")
    assert result is not None
    assert result["threat_actors"][0]["is_watched"] is True


async def test_matches_attack_group_by_alias_case_insensitive(
    async_db_session: AsyncSession,
) -> None:
    async_db_session.add(
        AttackGroup(
            stix_id="intrusion-set--abc123",
            group_id="G0096",
            name="APT41",
            aliases=["Wicked Panda", "Double Dragon"],
            domains=["enterprise-attack"],
        )
    )
    await async_db_session.flush()

    article_repo = AsyncArticleRepo(async_db_session)
    article = await article_repo.upsert(url="https://example.com/a4", title="A4", source="X")
    await article_repo.set_enrichment(article, threat_actors=["wicked panda"])

    ioc_repo = AsyncIndicatorRepo(async_db_session)
    await ioc_repo.upsert(
        type="domain",
        value="matched.example",
        source_url="https://x.com",
        source_name="x",
        article_id=article.id,
    )

    result = await svc.get_ioc_ta_links(async_db_session, "domain", "matched.example")
    assert result is not None
    entry = result["threat_actors"][0]
    assert entry["attack_group_id"] == "G0096"
    assert entry["attack_group_name"] == "APT41"
    assert "Wicked Panda" in entry["attack_group_aliases"]
