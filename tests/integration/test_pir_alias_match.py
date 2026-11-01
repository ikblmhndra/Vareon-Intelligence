"""Pembaca layanan P7c Task 12 di Postgres beneran: kriteria PIR menyimpan nama apa adanya tapi
dicocokkan lewat `entity_aliases` (spec 5.1) di SEMUA jalur pencocokan (filter artikel, crossref
CVE/TA, PIR per campaign), dan tautan IOC -> TA membaca nama entitas hidup dari mention."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services import campaign as campaign_service
from cti_api.services import crossref as crossref_service
from cti_api.services import ioc_ta_links
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.entity import Entity, EntityMention
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from cti_core.db.repositories.ta import AsyncTARepo
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.entity_support import seed_entity

pytestmark = pytest.mark.asyncio


async def _seed_actor(session: AsyncSession, name: str, *aliases: str) -> Entity:
    return await session.run_sync(
        lambda s: seed_entity(s, "intrusion-set", name, *aliases, source="galaxy")
    )


async def test_pir_actor_criterion_matches_alias(async_db_session: AsyncSession) -> None:
    """Kriteria "apt36" menemukan artikel/CVE/campaign yang menyebut "Transparent Tribe"."""
    s = async_db_session
    await AsyncClientRepo(s).ensure_default()
    tribe = await _seed_actor(s, "Transparent Tribe", "APT36")

    article_repo = AsyncArticleRepo(s)
    article = await article_repo.upsert(
        url="https://example.com/pir-alias",
        title="CVE-2026-3636 used by Transparent Tribe",
        source="S",
        posted_on=datetime.date.today(),
    )
    await article_repo.set_enrichment(article, threat_actors=["Transparent Tribe"])

    cve = CveTracker(cve_id="CVE-2026-3636", client_id="default", tech="nginx")
    s.add(cve)
    await s.flush()
    s.add(
        EntityMention(
            cve_tracker_id=cve.id,
            entity_id=tribe.id,
            method="legacy",
            matched_alias="Transparent Tribe",
        )
    )
    await s.flush()

    pir = await AsyncPIRRepo(s).create(
        {"title": "Track APT36", "criteria": {"threat_actors": ["apt36"]}}, client_id="default"
    )

    # filter artikel (repo, Task 11)
    articles, total = await AsyncPIRRepo(s).list_articles_for_pir(
        pir, article_repo, page=1, page_size=10
    )
    assert total == 1 and [a.id for a in articles] == [article.id]

    # crossref CVE: aktor CVE/artikel (nama entitas) beririsan dengan kriteria lewat alias
    by_cve = await crossref_service.get_cve_crossrefs(s, "CVE-2026-3636", "default")
    assert [(p["id"], p["ta_overlap"]) for p in by_cve["matched_pirs"]] == [
        (pir.id, ["Transparent Tribe"])
    ]

    # crossref PIR: overlap aktor CVE dihitung lewat alias
    by_pir = await crossref_service.get_pir_crossrefs(s, pir.id, "default")
    assert [(c["cve_id"], c["ta_overlap"]) for c in by_pir["matched_cves"]] == [
        ("CVE-2026-3636", ["Transparent Tribe"])
    ]

    # crossref TA: PIR aktif yang menyimpan alias ikut terdaftar untuk nama kanonik
    by_actor = await crossref_service.get_ta_crossrefs(s, "Transparent Tribe", "default")
    assert [p["id"] for p in by_actor["active_pirs"]] == [pir.id]

    # PIR per campaign (cluster dominan "Transparent Tribe")
    clusters: list[dict[str, object]] = [
        {"dominant_tas": ["Transparent Tribe"], "dominant_industries": [], "dominant_countries": []}
    ]
    await campaign_service._match_pirs(s, clusters, "default")  # type: ignore[arg-type]
    assert [p["id"] for p in clusters[0]["matched_pirs"]] == [pir.id]  # type: ignore[index]


async def test_ioc_ta_links_uses_entity_names(async_db_session: AsyncSession) -> None:
    """Tag analis "apt36" dan mention artikel "Transparent Tribe" = SATU aktor (nama entitas);
    aktor suppressed tidak tampil; status watch dicocokkan lewat alias."""
    s = async_db_session
    await AsyncClientRepo(s).ensure_default()
    await _seed_actor(s, "Transparent Tribe", "APT36")
    noisy = await _seed_actor(s, "NoisyName")

    article_repo = AsyncArticleRepo(s)
    article = await article_repo.upsert(
        url="https://example.com/ioc-alias", title="Tribe", source="X"
    )
    await article_repo.set_enrichment(article, threat_actors=["Transparent Tribe", "NoisyName"])
    await s.execute(update(Entity).where(Entity.id == noisy.id).values(suppressed=True))

    ioc_repo = AsyncIndicatorRepo(s)
    created = await ioc_repo.upsert(
        type="domain",
        value="tribe.example",
        source_url="https://x.com",
        source_name="x",
        article_id=article.id,
    )
    ioc = await ioc_repo.get_by_id(created.id)
    assert ioc is not None
    await ioc_repo.add_threat_actors(ioc, ["apt36"])
    await AsyncTARepo(s).add_to_watchlist("APT36", "default")
    s.expire_all()

    result = await ioc_ta_links.get_ioc_ta_links(s, "domain", "tribe.example")
    assert result is not None
    assert [
        (t["name"], t["article_count"], t["source"], t["is_watched"])
        for t in result["threat_actors"]
    ] == [("Transparent Tribe", 1, "both", True)]


async def test_malware_criterion_via_alias(async_db_session: AsyncSession) -> None:
    """Kriteria malware "lumma" menemukan artikel yang menyebut "Lumma Stealer" lewat alias."""
    s = async_db_session
    await AsyncClientRepo(s).ensure_default()
    await s.run_sync(
        lambda sync: seed_entity(sync, "malware", "Lumma Stealer", "Lumma", source="attack")
    )
    article_repo = AsyncArticleRepo(s)
    article = await article_repo.upsert(
        url="https://example.com/pir-malware-alias",
        title="Infostealer campaign",
        source="S",
        posted_on=datetime.date.today(),
    )
    await article_repo.set_enrichment(article, malware=[("Lumma Stealer", "malware")])
    await article_repo.upsert(
        url="https://example.com/pir-malware-other",
        title="Unrelated",
        source="S",
        posted_on=datetime.date.today(),
    )
    pir = await AsyncPIRRepo(s).create(
        {"title": "Track Lumma", "criteria": {"malware": ["lumma"]}}, client_id="default"
    )
    articles, total = await AsyncPIRRepo(s).list_articles_for_pir(
        pir, article_repo, page=1, page_size=10
    )
    assert total == 1 and [a.id for a in articles] == [article.id]


async def test_pir_malware_criterion_matches_campaign_cluster(
    async_db_session: AsyncSession,
) -> None:
    """Kriteria malware "lumma" cocok dengan cluster yang artikelnya menyebut "Lumma Stealer"
    (lewat alias); cluster dengan malware lain tidak cocok."""
    s = async_db_session
    await AsyncClientRepo(s).ensure_default()
    await s.run_sync(
        lambda sync: seed_entity(sync, "malware", "Lumma Stealer", "Lumma", source="attack")
    )
    pir = await AsyncPIRRepo(s).create(
        {"title": "Track Lumma", "criteria": {"malware": ["lumma"]}}, client_id="default"
    )
    base: dict[str, object] = {
        "dominant_tas": [],
        "dominant_industries": [],
        "dominant_countries": [],
    }
    clusters: list[dict[str, object]] = [
        {**base, "_malware": ["Lumma Stealer"]},
        {**base, "_malware": ["Emotet"]},
    ]
    await campaign_service._match_pirs(s, clusters, "default")  # type: ignore[arg-type]
    assert [p["id"] for p in clusters[0]["matched_pirs"]] == [pir.id]  # type: ignore[index]
    assert clusters[1]["matched_pirs"] == []
    assert "_malware" not in clusters[0]
