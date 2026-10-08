"""Port `cve_priority_service.py`. Fase 7.4 Grup A (2026-09-23). BEDA
dari 5 file Grup A lain -- ini bukan cuma internal helper `campaign.py`
(dipanggil per-cluster buat `prioritized_cves`), tapi JUGA backing
endpoint standalone `GET /api/cve/prioritize` (router `cve.py`, ad-hoc
prioritization di luar konteks campaign apa pun).

`_fetch_tech_stack_names()` legacy punya asimetri "default ATAU field
client_id gak ada" -- SAMA kelas asimetri yang udah diselesaikan
`AsyncPIRRepo.list_active_by_client()` (Grup A ini juga): artefak
migrasi era Mongo, gak relevan lagi di skema baru (`TechStackEntry.
client_id` NOT NULL). `AsyncTechStackRepo.list_filtered(client_id=...)`
udah scope biasa, dipakai apa adanya.

Parameter `campaign_context: dict` legacy DI-DROP -- gak pernah dibaca
sama sekali di badan fungsi aslinya (dead parameter, keduanya caller
legacy ngirim `{}` atau campaign dict yang gak kepake). Bukan
penyederhanaan sembarangan, ketauan lewat baca kode lama utuh."""

from __future__ import annotations

from typing import Any

from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.db.repositories.techstack import AsyncTechStackRepo
from sqlalchemy.ext.asyncio import AsyncSession


def _priority_label(score: float) -> str:
    if score >= 80:
        return "critical_patch"
    if score >= 60:
        return "high_priority"
    if score >= 40:
        return "medium"
    return "low"


def _patch_urgency(label: str, in_tech_stack: bool) -> str:
    if label == "critical_patch" and in_tech_stack:
        return "immediate"
    if label == "critical_patch":
        return "24h"
    if label == "high_priority":
        return "7d"
    if label == "medium":
        return "30d"
    return "monitor"


async def prioritize_campaign_cves(
    session: AsyncSession, cve_ids: list[str], *, client_id: str = "default"
) -> list[dict[str, Any]]:
    if not cve_ids:
        return []

    rows = await AsyncCveTrackerRepo(session).list_by_cve_ids_any_client(cve_ids)
    # Satu CVE bisa punya baris per client dengan `tech` berbeda. Baris client yang bertanya
    # menang; baris client lain hanya cadangan kalau CVE-nya belum di-track client ini.
    tracker_map: dict[str, CveTracker] = {}
    for r in rows:
        key = r.cve_id.upper()
        if key not in tracker_map or r.client_id == client_id:
            tracker_map[key] = r

    tech_entries, _total = await AsyncTechStackRepo(session).list_filtered(
        client_id=client_id, page=1, page_size=10000
    )
    tech_stack = {e.name.lower() for e in tech_entries if e.name}

    results: list[dict[str, Any]] = []
    for cve_id in cve_ids:
        row = tracker_map.get(cve_id.upper())
        if row is None:
            results.append(
                {
                    "cve_id": cve_id,
                    "cvss_score": None,
                    "severity": None,
                    "cisa_kev": False,
                    "poc_available": False,
                    "actively_exploited": False,
                    "in_tech_stack": False,
                    "priority_score": 20,
                    "priority_label": "low",
                    "patch_urgency": "monitor",
                }
            )
            continue

        cvss = float(row.cve_score or 0)
        cisa_kev = bool(row.cisa_kev)
        actively_exploited = bool(row.active_exploitation)
        poc_available = bool(row.poc_available)
        tech_name = (row.tech or "").lower()
        in_tech_stack = bool(
            tech_name and any(t in tech_name or tech_name in t for t in tech_stack)
        )

        score = (
            cvss * 10 * 0.30
            + (100 if cisa_kev else 0) * 0.20
            + (100 if actively_exploited else 0) * 0.20
            + (100 if poc_available else 0) * 0.10
            + (100 if in_tech_stack else 0) * 0.20
        )
        score = round(min(score, 100), 1)

        label = _priority_label(score)
        results.append(
            {
                "cve_id": cve_id,
                "cvss_score": cvss if cvss > 0 else None,
                "severity": row.cve_severity,
                "cisa_kev": cisa_kev,
                "poc_available": poc_available,
                "actively_exploited": actively_exploited,
                "in_tech_stack": in_tech_stack,
                "priority_score": score,
                "priority_label": label,
                "patch_urgency": _patch_urgency(label, in_tech_stack),
            }
        )

    results.sort(key=lambda x: x["priority_score"], reverse=True)
    return results
