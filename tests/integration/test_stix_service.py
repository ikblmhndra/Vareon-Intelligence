"""Integration test `cti_api.services.stix` -- Postgres REAL
(testcontainers). Fase 7.3 (router `stix`, Bagian 4). Builder ini
STATELESS (baca-transform doang), jadi test-nya fokus ke BENTUK bundle
STIX yang dihasilkan dari data seed, bukan CRUD/cache."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from cti_api.services import stix as stix_service
from cti_core.db.models.pir import PIRRequirement
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from cti_core.db.repositories.ta import AsyncTAProfileRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _ensure_clients(session: AsyncSession) -> None:
    await AsyncClientRepo(session).ensure_default()


def _types(bundle: dict[str, Any]) -> list[str]:
    return [o["type"] for o in bundle["objects"]]


# ── build_article_stix_bundle ────────────────────────────────────────────────


async def test_build_article_stix_bundle(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    article_repo = AsyncArticleRepo(async_db_session)
    article = await article_repo.upsert(
        url="https://example.com/apt41-campaign",
        title="APT41 spearphishing campaign",
        source="example",
        posted_on=datetime.date(2026, 9, 1),
    )
    await article_repo.set_enrichment(
        article,
        threat_actors=["Apt41"],
        ttps=[("T1566", "Phishing")],
    )

    bundle = await stix_service.build_article_stix_bundle(async_db_session, article.id)
    assert bundle is not None
    assert bundle["type"] == "bundle"
    types = _types(bundle)
    assert types.count("identity") == 1
    assert "report" in types
    assert "threat-actor" in types
    assert "attack-pattern" in types
    assert "relationship" in types

    report = next(o for o in bundle["objects"] if o["type"] == "report")
    assert report["name"] == "APT41 spearphishing campaign"
    assert report["published"] == "2026-09-01T00:00:00Z"
    assert report["external_references"][0]["url"] == "https://example.com/apt41-campaign"


async def test_build_article_stix_bundle_missing_returns_none(
    async_db_session: AsyncSession,
) -> None:
    result = await stix_service.build_article_stix_bundle(async_db_session, 999999)
    assert result is None


# ── build_ta_stix_bundle ─────────────────────────────────────────────────────


async def test_build_ta_stix_bundle_with_profile(async_db_session: AsyncSession) -> None:
    await AsyncTAProfileRepo(async_db_session).save_profile(
        "Apt41",
        {
            "identity": {"primary_name": "APT41", "actor_type": "nation-state"},
            "motivation": {"primary_motivation": "espionage"},
            "capability_assessment": {
                "sophistication_level": "advanced",
                "attack_techniques": {"initial-access": ["T1566 Phishing"]},
                "known_malware": [{"name": "ShadowPad", "type": "backdoor"}],
            },
            "infrastructure": {
                "known_iocs": {"domains": ["evil[.]example[.]com"], "ips": ["1.2.3.4"]}
            },
        },
    )

    bundle = await stix_service.build_ta_stix_bundle(async_db_session, "apt41")
    types = _types(bundle)
    assert "threat-actor" in types
    assert "attack-pattern" in types
    assert "malware" in types
    assert "indicator" in types

    indicator = next(
        o for o in bundle["objects"] if o["type"] == "indicator" and "domain-name" in o["pattern"]
    )
    # `[.]` defang harus dibalikin jadi `.` beneran
    assert "evil.example.com" in indicator["pattern"]

    ta_obj = next(o for o in bundle["objects"] if o["type"] == "threat-actor")
    assert ta_obj["name"] == "APT41"


async def test_build_ta_stix_bundle_no_profile_returns_identity_only(
    async_db_session: AsyncSession,
) -> None:
    bundle = await stix_service.build_ta_stix_bundle(async_db_session, "NeverSeenActor")
    assert _types(bundle) == ["identity"]


# ── build_ioc_stix_bundle ────────────────────────────────────────────────────


async def test_build_ioc_stix_bundle(async_db_session: AsyncSession) -> None:
    ioc_repo = AsyncIOCRepo(async_db_session)
    await ioc_repo.upsert(
        type="ip", value="203.0.113.10", source_url="https://example.com/a", source_name="s"
    )
    await ioc_repo.upsert(
        type="domain", value="bad.example.com", source_url="https://example.com/b", source_name="s"
    )

    bundle = await stix_service.build_ioc_stix_bundle(async_db_session)
    types = _types(bundle)
    assert types.count("identity") == 1
    assert types.count("indicator") == 2

    bundle_ip_only = await stix_service.build_ioc_stix_bundle(async_db_session, ioc_type="ip")
    ip_indicators = [o for o in bundle_ip_only["objects"] if o["type"] == "indicator"]
    assert len(ip_indicators) == 1
    assert "203.0.113.10" in ip_indicators[0]["pattern"]


async def test_build_ioc_stix_bundle_empty(async_db_session: AsyncSession) -> None:
    bundle = await stix_service.build_ioc_stix_bundle(async_db_session)
    assert _types(bundle) == ["identity"]


# ── build_pir_stix_bundle ────────────────────────────────────────────────────


async def test_build_pir_stix_bundle_only_active_ordered_by_priority(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    pir_repo = AsyncPIRRepo(async_db_session)
    low = await pir_repo.create(
        {"title": "Low priority watch", "priority": "P3", "criteria": {}}, client_id="default"
    )
    high = await pir_repo.create(
        {"title": "High priority watch", "priority": "P1", "criteria": {}}, client_id="default"
    )
    inactive = await pir_repo.create(
        {"title": "Closed PIR", "priority": "P1", "criteria": {}}, client_id="default"
    )
    inactive_row = await async_db_session.get(PIRRequirement, inactive.id)
    assert inactive_row is not None
    inactive_row.status = "closed"
    await async_db_session.flush()

    bundle = await stix_service.build_pir_stix_bundle(async_db_session, "default")
    coas = [o for o in bundle["objects"] if o["type"] == "course-of-action"]
    names = [c["name"] for c in coas]
    assert names == [f"PIR: {high.title}", f"PIR: {low.title}"]
    assert all(c["x_pir_status"] == "active" for c in coas)

    relationships = [o for o in bundle["objects"] if o["type"] == "relationship"]
    assert len(relationships) == 2
    assert all(r["relationship_type"] == "derived-from" for r in relationships)
