"""Skor risiko CVE 0-100: satu rumus untuk `/prioritize` (Python) dan daftar CVE (SQL).

Rumus lama `cve_priority` (CVSS*10*0.30 + 20 KEV + 20 exploited + 10 PoC + 20 in-stack) dipindah ke
sini supaya `sort_by=risk` di SQL dan skor yang ditampilkan tidak bisa menyimpang. Bobot jadi
konstanta; `risk_score_sql` memakai konstanta yang sama.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, Float, case, func, literal

from cti_core.db.models.cve import CveTracker

W_CVSS = 0.30
W_KEV = 20.0
W_EXPLOITED = 20.0
W_POC = 10.0
W_IN_STACK = 20.0
RISK_MAX = 100.0


def risk_score(
    cvss: float | None, *, kev: bool, exploited: bool, poc: bool, in_stack: bool
) -> float:
    """Skor 0-100, 1 desimal, dibatasi `RISK_MAX`. `cvss` None dianggap 0."""
    score = (
        float(cvss or 0) * 10 * W_CVSS
        + (W_KEV if kev else 0.0)
        + (W_EXPLOITED if exploited else 0.0)
        + (W_POC if poc else 0.0)
        + (W_IN_STACK if in_stack else 0.0)
    )
    return round(min(score, RISK_MAX), 1)


def risk_label(score: float) -> str:
    if score >= 80:
        return "critical_patch"
    if score >= 60:
        return "high_priority"
    if score >= 40:
        return "medium"
    return "low"


def risk_score_sql(in_stack: ColumnElement[bool]) -> ColumnElement[float]:
    """Padanan SQL `risk_score` (tanpa pembulatan: cukup untuk mengurutkan). `in_stack` dihitung
    pemanggil (nama tech tracker ada di techstack client, lihat `list_filtered`)."""
    expr = (
        func.coalesce(CveTracker.cve_score, 0) * 10 * W_CVSS
        + case((CveTracker.cisa_kev, W_KEV), else_=0.0)
        + case((CveTracker.active_exploitation, W_EXPLOITED), else_=0.0)
        + case((CveTracker.poc_available, W_POC), else_=0.0)
        + case((in_stack, W_IN_STACK), else_=0.0)
    )
    return func.least(expr, literal(RISK_MAX, Float))
