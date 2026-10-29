"""Port `killchain_service.py` (109 baris) + `campaign_link_service.py`
(66 baris) + `campaign_scoring_service.py` (189 baris) -- 3 helper
analisis campaign digabung SATU file (Fase 7.4 Grup A, 2026-09-23), pola
sama kayak Grup B (`cve_lookup.py`): tiga file kecil, satu tema ("hitung
metrik satu/sepasang campaign"), SEMUA cuma dipanggil dari SATU tempat
(`cti_api.services.campaign.get_recent_campaigns()`), gak ada endpoint
router sendiri-sendiri.

`analyze_kill_chain()`/`compute_campaign_links()` pure, port apa adanya.

`compute_campaign_severity()`: `articles_raw` DIWAJIBKAN (bukan
`| None` opsional kayak legacy) -- satu-satunya caller legacy
(`get_recent_campaigns()`) SELALU ngirim ini terisi, cabang fallback-
query-DB-langsung legacy gak pernah kepanggil di praktiknya (dead code,
di-drop bukan disederhanain paksa).

TA sophistication lookup pakai `AsyncTAProfileRepo.list_profiles_by_
names()` (EXACT case-insensitive match) -- BEDA dari `$regex` alternation
legacy (substring match longgar). Keputusan konsisten sama lookup TA
profile yang sama dipakai `diamond_model.py`/`geopolitical.py` di Grup
A ini juga -- exact match lebih ketat (gak match parsial ke nama TA
lain yang kebetulan mirip), bukan disederhanain sembarangan."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from cti_core.db.repositories.ta import AsyncTAProfileRepo
from sqlalchemy.ext.asyncio import AsyncSession

# ── Kill chain (port `killchain_service.py` apa adanya) ──────────────────────

KILL_CHAIN_PHASES = [
    "initial_access", "execution", "persistence", "privilege_escalation",
    "defense_evasion", "credential_access", "discovery", "lateral_movement",
    "collection", "exfiltration", "command_and_control", "impact",
]  # fmt: skip

_TECHNIQUE_TACTIC: dict[str, str] = {
    "T1566": "initial_access", "T1190": "initial_access", "T1133": "initial_access",
    "T1200": "initial_access", "T1195": "initial_access", "T1189": "initial_access",
    "T1091": "initial_access", "T1078": "initial_access",
    "T1059": "execution", "T1204": "execution", "T1053": "execution",
    "T1569": "execution", "T1106": "execution", "T1129": "execution",
    "T1047": "execution", "T1559": "execution",
    "T1547": "persistence", "T1543": "persistence", "T1546": "persistence",
    "T1574": "persistence", "T1505": "persistence",
    "T1176": "persistence", "T1137": "persistence", "T1197": "persistence",
    "T1548": "privilege_escalation", "T1134": "privilege_escalation",
    "T1055": "privilege_escalation", "T1484": "privilege_escalation",
    "T1611": "privilege_escalation",
    "T1027": "defense_evasion", "T1036": "defense_evasion", "T1070": "defense_evasion",
    "T1562": "defense_evasion", "T1112": "defense_evasion", "T1140": "defense_evasion",
    "T1218": "defense_evasion", "T1497": "defense_evasion", "T1620": "defense_evasion",
    "T1003": "credential_access", "T1110": "credential_access", "T1555": "credential_access",
    "T1056": "credential_access", "T1539": "credential_access", "T1552": "credential_access",
    "T1558": "credential_access",
    "T1083": "discovery", "T1057": "discovery", "T1082": "discovery",
    "T1016": "discovery", "T1049": "discovery", "T1033": "discovery",
    "T1087": "discovery", "T1046": "discovery", "T1135": "discovery",
    "T1021": "lateral_movement", "T1534": "lateral_movement", "T1570": "lateral_movement",
    "T1550": "lateral_movement", "T1080": "lateral_movement",
    "T1560": "collection", "T1005": "collection", "T1025": "collection",
    "T1074": "collection", "T1113": "collection", "T1125": "collection",
    "T1123": "collection", "T1119": "collection",
    "T1041": "exfiltration", "T1048": "exfiltration", "T1567": "exfiltration",
    "T1029": "exfiltration", "T1030": "exfiltration",
    "T1071": "command_and_control", "T1095": "command_and_control", "T1572": "command_and_control",
    "T1090": "command_and_control", "T1219": "command_and_control", "T1102": "command_and_control",
    "T1568": "command_and_control", "T1573": "command_and_control",
    "T1486": "impact", "T1490": "impact", "T1498": "impact", "T1499": "impact",
    "T1529": "impact", "T1561": "impact", "T1485": "impact", "T1491": "impact",
}  # fmt: skip

_TECH_ID_RE = re.compile(r"\b(T\d{4})(?:\.\d+)?\b", re.IGNORECASE)


def analyze_kill_chain(attack_techniques: list[str]) -> dict[str, Any]:
    phase_techniques: dict[str, list[str]] = {p: [] for p in KILL_CHAIN_PHASES}

    for tech_str in attack_techniques:
        m = _TECH_ID_RE.search(tech_str)
        if not m:
            continue
        tid = m.group(1).upper()
        tactic = _TECHNIQUE_TACTIC.get(tid)
        if tactic:
            phase_techniques[tactic].append(tech_str)

    phases_covered = [p for p in KILL_CHAIN_PHASES if phase_techniques[p]]
    phases_missing = [p for p in KILL_CHAIN_PHASES if not phase_techniques[p]]
    completeness_score = round(len(phases_covered) / 12 * 100)

    if completeness_score >= 80:
        completeness_label = "full_chain"
    elif completeness_score >= 50:
        completeness_label = "partial_chain"
    else:
        completeness_label = "limited"

    chain_visualization = [
        {"phase": p, "covered": bool(phase_techniques[p]), "techniques": phase_techniques[p]}
        for p in KILL_CHAIN_PHASES
    ]

    has_initial = bool(phase_techniques["initial_access"])
    has_exec = bool(phase_techniques["execution"])
    has_exfil = bool(phase_techniques["exfiltration"])
    n_covered = len(phases_covered)

    if has_initial and has_exec and has_exfil:
        operational_risk = "critical"
    elif n_covered >= 8:
        operational_risk = "high"
    elif n_covered >= 5:
        operational_risk = "medium"
    else:
        operational_risk = "low"

    return {
        "phases_covered": phases_covered,
        "phases_missing": phases_missing,
        "completeness_score": completeness_score,
        "completeness_label": completeness_label,
        "chain_visualization": chain_visualization,
        "operational_risk": operational_risk,
    }


# ── Campaign links (port `campaign_link_service.py` apa adanya) ──────────────


def _link_jaccard(a: set[Any], b: set[Any]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _link_type(ta_j: float, ioc_j: float, ttp_j: float) -> str:
    if ta_j > 0.5:
        return "same_actor"
    if ioc_j > 0.3:
        return "shared_infra"
    if ttp_j > 0.4:
        return "similar_ttp"
    return "related"


def compute_campaign_links(campaigns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepped = []
    for c in campaigns:
        prepped.append(
            {
                "cluster_id": c["cluster_id"],
                "cluster_name": c.get("cluster_name", c.get("summary_title", c["cluster_id"])),
                "tas": set(c.get("dominant_tas", []) or []),
                "ttps": set(c.get("attack_techniques", []) or []),
                "iocs": {f"{i['type']}:{i['value']}" for i in (c.get("iocs") or [])},
                "cves": set(c.get("cve_ids", []) or []),
            }
        )

    links: list[dict[str, Any]] = []
    n = len(prepped)
    for i in range(n):
        a = prepped[i]
        for j in range(i + 1, n):
            b = prepped[j]
            ta_j = _link_jaccard(a["tas"], b["tas"])
            ttp_j = _link_jaccard(a["ttps"], b["ttps"])
            ioc_j = _link_jaccard(a["iocs"], b["iocs"])
            cve_j = _link_jaccard(a["cves"], b["cves"])

            score = round(40 * ta_j + 25 * ttp_j + 25 * ioc_j + 10 * cve_j, 2)
            if score <= 20:
                continue

            ltype = _link_type(ta_j, ioc_j, ttp_j)
            links.append(
                {
                    "source_id": a["cluster_id"],
                    "source_name": a["cluster_name"],
                    "target_id": b["cluster_id"],
                    "target_name": b["cluster_name"],
                    "score": score,
                    "shared_tas": sorted(a["tas"] & b["tas"]),
                    "shared_ttps": sorted(a["ttps"] & b["ttps"]),
                    "shared_iocs": sorted(a["iocs"] & b["iocs"]),
                    "link_type": ltype,
                }
            )

    return links


# ── Campaign severity scoring (port `campaign_scoring_service.py`) ───────────

_SOPHISTICATION_SCORES = {"nation-state": 100, "high": 75, "medium": 50, "low": 25}
_RELIABILITY_SCORES = {"A": 100, "B": 80, "C": 60, "D": 40, "E": 20, "F": 10}


async def _ta_sophistication_factor(session: AsyncSession, dominant_tas: list[str]) -> float:
    if not dominant_tas:
        return 50.0
    profiles = await AsyncTAProfileRepo(session).list_profiles_by_names(dominant_tas)
    best = 0
    for p in profiles:
        level = (p.profile.get("capability_assessment") or {}).get("sophistication_level", "")
        score = _SOPHISTICATION_SCORES.get((level or "").lower(), 0)
        best = max(best, score)
    return float(best) if best else 50.0


async def _ioc_confidence_factor(session: AsyncSession, iocs: list[dict[str, Any]]) -> float:
    ioc_ids = [ioc["id"] for ioc in iocs if isinstance(ioc.get("id"), int)]
    if not ioc_ids:
        return 50.0
    rows = await AsyncIndicatorRepo(session).list_by_ids(ioc_ids)
    scores = [r.confidence_score for r in rows if r.confidence_score is not None]
    return float(sum(scores) / len(scores)) if scores else 50.0


async def _cve_criticality_factor(session: AsyncSession, cve_ids: list[str]) -> float:
    if not cve_ids:
        return 0.0
    rows = await AsyncCveTrackerRepo(session).list_by_cve_ids_any_client(cve_ids)
    if not rows:
        return 0.0

    max_cvss = max((r.cve_score or 0.0) for r in rows)
    base = (max_cvss / 10.0) * 80.0

    bonus = 0.0
    for r in rows:
        if r.cisa_kev:
            bonus = max(bonus, 15.0)
        if r.active_exploitation:
            bonus = max(bonus, 20.0)
        if r.poc_available:
            bonus = max(bonus, 5.0)

    return min(100.0, base + bonus)


def _velocity_factor(velocity_articles_per_day: float) -> float:
    apd = velocity_articles_per_day or 0.0
    if apd >= 5.0:
        return 100.0
    if apd >= 3.0:
        return 80.0
    if apd >= 1.0:
        return 60.0
    if apd >= 0.3:
        return 40.0
    return 20.0


def _source_quality_factor(articles_raw: list[dict[str, Any]]) -> float:
    grades = [(a.get("source_reliability") or "").upper() for a in articles_raw]
    scores = [_RELIABILITY_SCORES[g] for g in grades if g in _RELIABILITY_SCORES]
    return float(sum(scores) / len(scores)) if scores else 50.0


async def compute_campaign_severity(
    session: AsyncSession, campaign: dict[str, Any], articles_raw: list[dict[str, Any]]
) -> dict[str, Any]:
    ta_f, ioc_f, cve_f = await asyncio.gather(
        _ta_sophistication_factor(session, campaign.get("dominant_tas", [])),
        _ioc_confidence_factor(session, campaign.get("iocs", [])),
        _cve_criticality_factor(session, campaign.get("cve_ids", [])),
    )
    src_f = _source_quality_factor(articles_raw)
    vel_f = _velocity_factor(campaign.get("velocity_articles_per_day", 0.0))

    severity_score = round(ta_f * 0.30 + ioc_f * 0.20 + cve_f * 0.20 + vel_f * 0.15 + src_f * 0.15)
    severity_score = max(0, min(100, severity_score))

    if severity_score >= 80:
        label = "critical"
    elif severity_score >= 60:
        label = "high"
    elif severity_score >= 40:
        label = "medium"
    else:
        label = "low"

    breakdown = {
        "ta_sophistication": round(ta_f * 0.30, 1),
        "ioc_confidence": round(ioc_f * 0.20, 1),
        "cve_criticality": round(cve_f * 0.20, 1),
        "campaign_velocity": round(vel_f * 0.15, 1),
        "source_quality": round(src_f * 0.15, 1),
        "raw": {
            "ta_sophistication": round(ta_f, 1),
            "ioc_confidence": round(ioc_f, 1),
            "cve_criticality": round(cve_f, 1),
            "campaign_velocity": round(vel_f, 1),
            "source_quality": round(src_f, 1),
        },
    }

    return {
        "severity_score": severity_score,
        "severity_label": label,
        "severity_breakdown": breakdown,
    }
