"""Port `ScraperNewsWeb/app/services/cross_reference_service.py` --
nyambungin CVE/PIR/TA lewat overlap threat_actors/TTPs. Fase 7.3 (router
`crossref`, Bagian 3, dikerjain TERAKHIR karena butuh `cve` [Bagian 1],
`pir` [Bagian 2], `ta_groups` [Bagian 3, TA profile] semua udah ada).

**CVE tracker dan PIR di-scope ke client aktif** (`client_id`, dari `X-Client-ID`). Port awal
memakai query lintas client seperti kode lama, sehingga user satu client bisa membaca PIR dan tech
stack (CVE yang di-track) client lain lewat `/api/crossref/*` (audit keamanan 2026-10-24). Artikel
dan profil TA tetap korpus bersama.

False positive dinilai per BARIS client (`is_false_positive_row`): CVE baru ditolak/disembunyikan
bila SEMUA barisnya ditandai FP oleh clientnya masing-masing. Dulu himpunan FP dari client mana
pun dipakai, sehingga satu client yang menandai FP menyembunyikan CVE itu dari client lain."""

from __future__ import annotations

from typing import Any

from cti_core.db.models.pir import PIRRequirement
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from cti_core.db.repositories.ta import AsyncTAProfileRepo
from sqlalchemy.ext.asyncio import AsyncSession


def _pir_out(pir: PIRRequirement, ta_overlap: set[str], ttp_overlap: set[str]) -> dict[str, Any]:
    return {
        "id": pir.id,
        "title": pir.title,
        "priority": pir.priority,
        "owner": pir.owner,
        "ta_overlap": sorted(ta_overlap),
        "ttp_overlap": sorted(ttp_overlap),
    }


def _profile_summary(actor_name: str, profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "actor_name": actor_name,
        "primary_name": (profile.get("identity") or {}).get("primary_name", ""),
        "actor_type": (profile.get("identity") or {}).get("actor_type", ""),
        "motivation": (profile.get("motivation") or {}).get("primary_motivation", ""),
        "monitoring_priority": (profile.get("organizational_relevance") or {}).get(
            "monitoring_priority", ""
        ),
        "confidence": (profile.get("profile_metadata") or {}).get("analyst_confidence", ""),
        "generated_at": profile.get("_generated_at", ""),
    }


async def get_cve_crossrefs(session: AsyncSession, cve_id: str, client_id: str) -> dict[str, Any]:
    repo = AsyncCveTrackerRepo(session)
    cve = await repo.get_by_cve_id_any_client(
        cve_id, exclude_false_positives=True, client_id=client_id
    )
    if cve is None:
        if await repo.get_by_cve_id_any_client(cve_id, client_id=client_id) is None:
            return {"error": "CVE not found"}
        return {"error": "CVE is a false positive"}

    cve_tas = {t.threat_actor for t in cve.threat_actors}
    cve_ttps = {t.ttp_id for t in cve.ttps}

    articles, _ = await AsyncArticleRepo(session).list_filtered(
        title_keywords=[cve_id], page=1, page_size=20
    )
    article_tas: set[str] = set(cve_tas)
    for a in articles:
        for t in a.threat_actors:
            article_tas.add(t.threat_actor)

    active_pirs = await AsyncPIRRepo(session).list_active_by_client(client_id)
    matched_pirs = []
    for pir in active_pirs:
        pir_tas = set(pir.criteria.get("threat_actors", []))
        pir_ttps = set(pir.criteria.get("ttps", []))
        ta_overlap = pir_tas & article_tas
        ttp_overlap = pir_ttps & cve_ttps
        if ta_overlap or ttp_overlap:
            matched_pirs.append(_pir_out(pir, ta_overlap, ttp_overlap))

    ta_profiles = []
    if article_tas:
        rows = await AsyncTAProfileRepo(session).list_profiles_by_names(list(article_tas))
        ta_profiles = [_profile_summary(r.actor_name, r.profile) for r in rows]

    return {
        "cve_id": cve_id,
        "cve_severity": cve.cve_severity or "",
        "cve_score": cve.cve_score,
        "tech": cve.tech or "",
        "cisa_kev": cve.cisa_kev,
        "poc_available": cve.poc_available,
        "matched_pirs": matched_pirs,
        "ta_profiles": ta_profiles,
        "news_articles": [
            {
                "_id": str(a.id),
                "title": a.title,
                "url": a.url,
                "posted_on": a.posted_on.isoformat() if a.posted_on else None,
                "source": a.source,
                "threat_actors": [t.threat_actor for t in a.threat_actors],
            }
            for a in articles
        ],
        "all_context_actors": sorted(article_tas),
    }


async def get_pir_crossrefs(session: AsyncSession, pir_id: int, client_id: str) -> dict[str, Any]:
    pir = await AsyncPIRRepo(session).get_by_id(pir_id)
    # PIR client lain dijawab sama dengan PIR yang tidak ada: keberadaannya tidak bocor.
    if pir is None or pir.client_id != client_id:
        return {"error": "PIR not found"}

    criteria = pir.criteria
    pir_tas: list[str] = criteria.get("threat_actors", [])
    pir_ttps = set(criteria.get("ttps", []))
    pir_industries: list[str] = criteria.get("industries", [])

    matched_cves_rows = await AsyncCveTrackerRepo(session).search_crossref(
        threat_actors=pir_tas, ttp_ids=list(pir_ttps), tech_list=pir_industries, client_id=client_id
    )

    matched_cves = []
    pir_tas_lower = {t.lower() for t in pir_tas}
    for c in matched_cves_rows:
        c_ta_set = {t.threat_actor for t in c.threat_actors}
        c_ttp_set = {t.ttp_id for t in c.ttps}
        matched_cves.append(
            {
                "cve_id": c.cve_id,
                "severity": c.cve_severity or "",
                "score": c.cve_score,
                "tech": c.tech or "",
                "cisa_kev": c.cisa_kev,
                "poc_available": c.poc_available,
                "ta_overlap": sorted({t for t in c_ta_set if t.lower() in pir_tas_lower}),
                "ttp_overlap": sorted(pir_ttps & c_ttp_set),
            }
        )

    ta_profiles = []
    if pir_tas:
        rows = await AsyncTAProfileRepo(session).list_profiles_by_names(pir_tas)
        profiled = {r.actor_name.lower(): r for r in rows}
        for ta in pir_tas:
            row = profiled.get(ta.lower())
            if row is not None:
                summary = _profile_summary(row.actor_name, row.profile)
                summary["has_profile"] = True
                ta_profiles.append(summary)
            else:
                ta_profiles.append({"actor_name": ta, "has_profile": False})

    return {
        "pir_id": pir.id,
        "pir_title": pir.title,
        "pir_priority": pir.priority,
        "matched_cves": matched_cves,
        "ta_profiles": ta_profiles,
        "pir_actors": pir_tas,
        "pir_ttps": list(pir_ttps),
    }


async def get_ta_crossrefs(
    session: AsyncSession, actor_name: str, client_id: str
) -> dict[str, Any]:
    cves = await AsyncCveTrackerRepo(session).get_by_threat_actor_exact(
        actor_name, client_id=client_id
    )
    active_pirs = await AsyncPIRRepo(session).list_active_by_client(client_id)
    pirs = [p for p in active_pirs if actor_name in p.criteria.get("threat_actors", [])]
    articles, _ = await AsyncArticleRepo(session).list_filtered(
        threat_actors=[actor_name], page=1, page_size=20
    )
    profile_row = await AsyncTAProfileRepo(session).get_profile(actor_name)
    profile_summary = None
    if profile_row is not None:
        profile_summary = {
            **{
                k: v
                for k, v in profile_row.profile.items()
                if k
                in (
                    "identity",
                    "motivation",
                    "targeting_profile",
                    "organizational_relevance",
                    "profile_metadata",
                )
            },
            "_generated_at": profile_row.generated_at.isoformat(),
        }

    return {
        "actor_name": actor_name,
        "has_profile": profile_row is not None,
        "profile_summary": profile_summary,
        "matched_cves": [
            {
                "cve_id": c.cve_id,
                "severity": c.cve_severity or "",
                "score": c.cve_score,
                "tech": c.tech or "",
                "cisa_kev": c.cisa_kev,
                "poc_available": c.poc_available,
            }
            for c in cves
        ],
        "active_pirs": [
            {"id": p.id, "title": p.title, "priority": p.priority, "owner": p.owner} for p in pirs
        ],
        "recent_articles": [
            {
                "title": a.title,
                "url": a.url,
                "posted_on": a.posted_on.isoformat() if a.posted_on else None,
                "source": a.source,
            }
            for a in articles
        ],
    }
