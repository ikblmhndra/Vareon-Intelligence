"""Integration test `cti_api.services.crossref` -- Postgres REAL
(testcontainers). Fase 7.3 (router `crossref`, Bagian 3, dikerjain
terakhir karena butuh cve/pir/ta_groups semua)."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services import crossref as crossref_service
from cti_core.db.models.cve import CveThreatActor, CveTracker, CveTTP
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from cti_core.db.repositories.ta import AsyncTAProfileRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _ensure_clients(session: AsyncSession) -> None:
    repo = AsyncClientRepo(session)
    await repo.ensure_default()


async def _seed(session: AsyncSession) -> dict[str, object]:
    await _ensure_clients(session)

    cve = CveTracker(
        cve_id="CVE-2026-1234",
        client_id="default",
        tech="WordPress",
        cve_score=9.8,
        cve_severity="CRITICAL",
        cisa_kev=True,
    )
    cve.threat_actors = [CveThreatActor(threat_actor="Apt41")]
    cve.ttps = [CveTTP(ttp_id="T1059", ttp_name="Command Scripting")]
    session.add(cve)

    fp_cve = CveTracker(cve_id="CVE-2020-0001", client_id="default", tech="OldStuff")
    session.add(fp_cve)
    await session.flush()

    await AsyncCveFalsePositiveRepo(session).mark("CVE-2020-0001", "default")

    article_repo = AsyncArticleRepo(session)
    a1 = await article_repo.upsert(
        url="https://example.com/cve-2026-1234-exploited",
        title="CVE-2026-1234 actively exploited in the wild",
        source="s",
        posted_on=datetime.date.today(),
    )
    await article_repo.set_enrichment(a1, threat_actors=["Apt41", "Turla"])

    pir_repo = AsyncPIRRepo(session)
    pir = await pir_repo.create(
        {"title": "Track APT41", "criteria": {"threat_actors": ["Apt41"], "ttps": ["T1059"]}},
        client_id="default",
    )

    await AsyncTAProfileRepo(session).save_profile(
        "Apt41",
        {
            "identity": {"primary_name": "APT41", "actor_type": "nation-state"},
            "motivation": {"primary_motivation": "espionage"},
            "organizational_relevance": {"monitoring_priority": "high"},
            "profile_metadata": {"analyst_confidence": "high"},
        },
    )
    await session.flush()
    return {"cve_id": cve.cve_id, "pir_id": pir.id}


async def test_get_cve_crossrefs_matches_pir_and_ta_profile(async_db_session: AsyncSession) -> None:
    seeded = await _seed(async_db_session)
    result = await crossref_service.get_cve_crossrefs(async_db_session, str(seeded["cve_id"]))

    assert result["cve_severity"] == "CRITICAL"
    assert result["cisa_kev"] is True
    assert len(result["matched_pirs"]) == 1
    assert result["matched_pirs"][0]["id"] == seeded["pir_id"]
    assert "Apt41" in result["matched_pirs"][0]["ta_overlap"]
    assert "T1059" in result["matched_pirs"][0]["ttp_overlap"]
    assert len(result["ta_profiles"]) == 1
    assert result["ta_profiles"][0]["actor_name"] == "Apt41"
    assert "Apt41" in result["all_context_actors"]
    assert "Turla" in result["all_context_actors"]


async def test_get_cve_crossrefs_false_positive_rejected(async_db_session: AsyncSession) -> None:
    await _seed(async_db_session)
    result = await crossref_service.get_cve_crossrefs(async_db_session, "CVE-2020-0001")
    assert result == {"error": "CVE is a false positive"}


async def test_get_cve_crossrefs_not_found(async_db_session: AsyncSession) -> None:
    result = await crossref_service.get_cve_crossrefs(async_db_session, "CVE-9999-9999")
    assert result == {"error": "CVE not found"}


async def test_get_pir_crossrefs_matches_cve(async_db_session: AsyncSession) -> None:
    seeded = await _seed(async_db_session)
    result = await crossref_service.get_pir_crossrefs(async_db_session, int(seeded["pir_id"]))  # type: ignore[arg-type]

    assert result["pir_title"] == "Track APT41"
    assert len(result["matched_cves"]) == 1
    assert result["matched_cves"][0]["cve_id"] == "CVE-2026-1234"
    assert "Apt41" in result["matched_cves"][0]["ta_overlap"]
    assert "T1059" in result["matched_cves"][0]["ttp_overlap"]
    assert result["ta_profiles"][0]["has_profile"] is True


async def test_get_pir_crossrefs_not_found(async_db_session: AsyncSession) -> None:
    result = await crossref_service.get_pir_crossrefs(async_db_session, 999999)
    assert result == {"error": "PIR not found"}


async def test_get_ta_crossrefs(async_db_session: AsyncSession) -> None:
    await _seed(async_db_session)
    result = await crossref_service.get_ta_crossrefs(async_db_session, "Apt41")

    assert result["has_profile"] is True
    assert result["profile_summary"]["identity"]["primary_name"] == "APT41"
    assert len(result["matched_cves"]) == 1
    assert result["matched_cves"][0]["cve_id"] == "CVE-2026-1234"
    assert len(result["active_pirs"]) == 1
    assert result["active_pirs"][0]["title"] == "Track APT41"
    assert len(result["recent_articles"]) == 1


async def test_get_ta_crossrefs_no_profile(async_db_session: AsyncSession) -> None:
    await _seed(async_db_session)
    result = await crossref_service.get_ta_crossrefs(async_db_session, "NeverSeenActor")
    assert result["has_profile"] is False
    assert result["profile_summary"] is None
    assert result["matched_cves"] == []


async def test_pir_and_actor_crossrefs_list_a_cve_tracked_by_two_clients_once(
    async_db_session: AsyncSession,
) -> None:
    """Tracker menyimpan satu baris PER CLIENT: CVE yang valid di dua client dulu muncul dua kali
    (dan memakai dua slot dari batas 50/30). Sekarang satu per `cve_id`, baris terkuat (skor CVSS
    tertinggi) yang mewakili."""
    clients = AsyncClientRepo(async_db_session)
    await clients.ensure_default()
    await clients.create(client_id="acme", name="Acme", countries=[])
    for client_id, score in (("default", 7.0), ("acme", 9.8)):
        row = CveTracker(cve_id="CVE-2026-7777", client_id=client_id, tech="nginx", cve_score=score)
        row.threat_actors = [CveThreatActor(threat_actor="Apt41")]
        async_db_session.add(row)
    async_db_session.add(
        CveTracker(cve_id="CVE-2026-7778", client_id="default", tech="nginx", cve_score=5.0)
    )
    await async_db_session.flush()
    pir = await AsyncPIRRepo(async_db_session).create(
        {"title": "Watch nginx", "criteria": {"industries": ["nginx"]}}, client_id="default"
    )

    by_pir = await crossref_service.get_pir_crossrefs(async_db_session, pir.id)
    by_actor = await crossref_service.get_ta_crossrefs(async_db_session, "Apt41")

    assert [c["cve_id"] for c in by_pir["matched_cves"]] == ["CVE-2026-7777", "CVE-2026-7778"]
    assert by_pir["matched_cves"][0]["score"] == 9.8
    assert [c["cve_id"] for c in by_actor["matched_cves"]] == ["CVE-2026-7777"]
