"""Port `ScraperNewsWeb/app/services/exec_dashboard_service.py` +
`exec_dashboard_v2_service.py`. Fase 7.3 (router `exec_dashboard`,
Bagian 5).

**Semua query di sini SEKUENSIAL** (bukan `asyncio.gather` kayak lama) --
satu `AsyncSession` gak aman dipakai concurrent, constraint yang sama
udah didokumentasikan berkali-kali sesi ini (`AsyncPIRRepo.list_pirs()`,
`pkg_vuln.scan_all_packages()`, `spike.py`). Dashboard-v2 aja manggil
~15 query terpisah -- lebih lambat dari `asyncio.gather` 15-way lama,
tapi satu-satunya cara aman lewat SQLAlchemy async session.

`_get_recent_clusters()`/`recent_clusters_summary` (Fase 7.4 Grup A,
2026-09-23) sekarang manggil `cti_api.services.campaign.get_recent_
campaigns()` beneran -- `try/except -> []` tetap dipertahankan (port
apa adanya, bukan cuma buat nutup gap lagi).

`_get_pending_fp_queue()` sekarang nyertain `id` (Fase 8 Grup F,
2026-09-25) -- legacy `exec.js` manggil kontrak FP-vote LAMA
(`POST /api/iocs/feedback`, body `{ioc_type,value,is_true_positive}`)
yang UDAH GAK ADA; kontrak baru (`POST /api/iocs/{ioc_id}/feedback`,
body `{verdict,note}`) butuh `ioc_id`, yang sebelumnya gak ke-serialize
di sini sama sekali (row cuma `value`/`type`/`last_seen`/
`confidence_score` -- gak cukup buat manggil endpoint yang bener).
Bukan perubahan skema DB, cuma nambah field yang emang udah ada di
`IOC` ORM object.

**`_get_critical_cves()` cuma filter `cisa_kev`** -- cabang `epss_score
>= 0.5` gak ada (kolom `epss_score` gak ada di `CveTracker`, lihat
docstring `cti_core.db.repositories.dashboard`)."""

from __future__ import annotations

import datetime
import statistics
from collections import defaultdict
from itertools import combinations
from typing import Any, TypedDict

from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services import campaign as campaign_service
from cti_api.services import spike as spike_service

NON_INCIDENT_TYPES = {
    "Vendor Report Article",
    "Unrelated Tech Stack Article",
    "Security Technology & Best Practices",
}


class _DateFilters(TypedDict):
    """Bentuk filter yang dipakai ULANG lintas hampir semua query
    `AsyncDashboardRepo` -- `TypedDict`, bukan `dict[str, Any]` polos,
    biar `**base`/`**prev_base` ke-typecheck bener lawan tanda tangan
    keyword masing-masing method (mypy gak bisa validasi splat dict
    heterogen kalau tipenya union polos)."""

    posted_on_start: datetime.date | None
    posted_on_end: datetime.date | None
    exclude_news_types: list[str] | None
    confirmed_only: bool


def build_view_config(role: str) -> dict[str, Any]:
    admin_set = {"admin", "superadmin"}
    return {
        "role": role,
        "sections": {
            "kpis": True,
            "sector_risk": True,
            "ta_leaderboard": True,
            "exec_brief_button": role in {"exec"} | admin_set,
            "source_reliability_spread": role in {"analyst"} | admin_set,
            "cluster_list": role in {"analyst"} | admin_set,
            "ioc_enrichment_hits": role in {"analyst", "soc"} | admin_set,
            "fp_feedback_queue": role in {"analyst"} | admin_set,
            "critical_cve_feed": role in {"soc"} | admin_set,
            "live_ioc_stream": role in {"soc"} | admin_set,
            "sigma_export_quick": role in {"soc"} | admin_set,
            "spike_alerts": role in {"soc", "analyst"} | admin_set,
        },
    }


# ── v1 ───────────────────────────────────────────────────────────────────────


async def get_exec_dashboard(
    session: AsyncSession, days: int = 90, incident_only: bool = True, confirmed_only: bool = False
) -> dict[str, Any]:
    repo = AsyncDashboardRepo(session)
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=days)
    prev_cut = today - datetime.timedelta(days=days * 2)

    exclude = sorted(NON_INCIDENT_TYPES) if incident_only else None
    base: _DateFilters = {
        "posted_on_start": cutoff,
        "posted_on_end": None,
        "exclude_news_types": exclude,
        "confirmed_only": confirmed_only,
    }
    prev_base: _DateFilters = {
        "posted_on_start": prev_cut,
        "posted_on_end": cutoff,
        "exclude_news_types": exclude,
        "confirmed_only": confirmed_only,
    }

    sector_trend_raw = await repo.monthly_industry_counts(**base)
    country_trend_raw = await repo.monthly_country_counts(**base)
    ta_raw = await repo.top_threat_actors(limit=10, **base)
    unique_ta_count = await repo.unique_threat_actor_count(**base)
    news_type_raw = await repo.news_type_breakdown(**base)
    prev_unique_ta_count = await repo.unique_threat_actor_count(**prev_base)
    prev_active_sectors = await repo.unique_industry_count(**prev_base)
    total = await repo.count_articles(**base)
    prev_total = await repo.count_articles(**prev_base)
    cve_raw = await repo.cve_tech_severity_breakdown(limit=10)

    months_set = {mo for _, mo, _ in sector_trend_raw}
    months = sorted(months_set)

    sector_map: dict[str, dict[str, int]] = {}
    for industry, mo, cnt in sector_trend_raw:
        sector_map.setdefault(industry, {})[mo] = cnt
    sector_totals = {s: sum(v.values()) for s, v in sector_map.items()}
    top_sectors = sorted(sector_totals, key=lambda x: -sector_totals[x])[:8]
    sector_trend = [
        {"sector": s, "data": [sector_map[s].get(m, 0) for m in months]} for s in top_sectors
    ]

    country_map: dict[str, dict[str, int]] = {}
    for country, mo, cnt in country_trend_raw:
        country_map.setdefault(country, {})[mo] = cnt
    country_totals = {c: sum(v.values()) for c, v in country_map.items()}
    top_countries = sorted(country_totals, key=lambda x: -country_totals[x])[:8]
    country_trend = [
        {"country": c, "data": [country_map[c].get(m, 0) for m in months]} for c in top_countries
    ]

    sector_heatmap = [
        {"sector": s, "months": [{"month": m, "count": sector_map[s].get(m, 0)} for m in months]}
        for s in top_sectors
    ]
    heatmap_max = max(
        (sector_map[s].get(m, 0) for s in top_sectors for m in months),
        default=0,
    )

    return {
        "total_incidents": total,
        "prev_total": prev_total,
        "unique_ta_count": unique_ta_count,
        "prev_unique_ta": prev_unique_ta_count,
        "active_sectors": len(top_sectors),
        "prev_active_sectors": prev_active_sectors,
        "months": months,
        "top_sectors": top_sectors,
        "top_countries": top_countries,
        "sector_trend": sector_trend,
        "country_trend": country_trend,
        "ta_leaderboard": [{"name": name, "count": cnt} for name, cnt in ta_raw],
        "news_type_breakdown": [
            {"name": nt or "Unknown", "count": cnt} for nt, cnt in news_type_raw
        ],
        "sector_heatmap": sector_heatmap,
        "heatmap_max": heatmap_max,
        "cve_exposure": cve_raw,
    }


# ── v2 tier helpers -- port byte-identik ────────────────────────────────────


def _compute_sector_risk_scores(sector_trend: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not sector_trend:
        return []

    all_last = [s["data"][-1] if s["data"] else 0 for s in sector_trend]
    max_last = max(all_last) or 1

    results: list[dict[str, Any]] = []
    for s in sector_trend:
        counts = s["data"]
        last = counts[-1] if counts else 0

        vol_score = (last / max_last) * 50

        if len(counts) >= 4:
            mid = len(counts) // 2
            first_avg = statistics.mean(counts[:mid]) if counts[:mid] else 0
            second_avg = statistics.mean(counts[mid:]) if counts[mid:] else 0
            if first_avg > 0:
                ratio = min(second_avg / first_avg, 2.0)
                trend_score = max(0, (ratio - 1.0) * 20)
            else:
                trend_score = 10 if second_avg > 0 else 0
        else:
            trend_score = 0

        if len(counts) >= 3:
            history = counts[:-1]
            mean = statistics.mean(history)
            try:
                std = statistics.stdev(history) if len(history) >= 2 else 0.5
            except statistics.StatisticsError:
                std = 0.5
            std = std or 0.5
            z = (last - mean) / std
            spike_score = min(30, max(0, z * 10))
        else:
            spike_score = 0

        results.append(
            {
                "sector": s["sector"],
                "risk_score": min(100, round(vol_score + trend_score + spike_score)),
            }
        )

    results.sort(key=lambda x: -x["risk_score"])
    return results


def _compute_ta_velocity(
    ta_monthly_raw: list[tuple[str, str, int]], months: list[str]
) -> list[dict[str, Any]]:
    series: dict[str, dict[str, int]] = defaultdict(dict)
    for actor, month, count in ta_monthly_raw:
        series[actor][month] = count

    results: list[dict[str, Any]] = []
    for actor, monthly in series.items():
        counts = [monthly.get(m, 0) for m in months]
        if len(counts) < 2 or sum(counts) == 0:
            continue
        last = counts[-1]
        prev = counts[:-1]
        avg_prev = statistics.mean(prev) if prev else 0
        if avg_prev > 0:
            velocity_pct = round((last / avg_prev - 1) * 100)
        elif last > 0:
            velocity_pct = 100
        else:
            velocity_pct = 0
        results.append(
            {
                "actor": actor,
                "velocity_pct": velocity_pct,
                "last_month": last,
                "avg_prev": round(avg_prev, 1),
                "total": sum(counts),
            }
        )

    results.sort(key=lambda x: -x["velocity_pct"])
    return results[:10]


def _compute_sector_cooccurrence(article_industries: dict[int, list[str]]) -> list[dict[str, Any]]:
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for industries in article_industries.values():
        unique = list(dict.fromkeys(i for i in industries if i))
        if len(unique) >= 2:
            for a, b in combinations(sorted(unique), 2):
                pair_counts[(a, b)] += 1

    results = [
        {"sector_a": a, "sector_b": b, "count": c}
        for (a, b), c in sorted(pair_counts.items(), key=lambda x: -x[1])
    ]
    return results[:15]


def _build_newstype_trend(
    nt_monthly_raw: list[tuple[str | None, str, int]], months: list[str], top_n: int = 6
) -> dict[str, Any]:
    monthly_map: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: dict[str, int] = defaultdict(int)
    for nt, mo, cnt in nt_monthly_raw:
        label = nt or "Unknown"
        monthly_map[label][mo] += cnt
        totals[label] += cnt

    top_types = sorted(totals, key=lambda x: -totals[x])[:top_n]
    series = [{"type": t, "data": [monthly_map[t].get(m, 0) for m in months]} for t in top_types]
    return {"months": months, "series": series}


def _build_sector_actor_matrix(
    sa_raw: list[tuple[str, str, int]], top_sectors: list[str], top_actors: list[str]
) -> dict[str, Any]:
    co_map = {(sector, actor): cnt for sector, actor, cnt in sa_raw}
    matrix = [[co_map.get((s, a), 0) for a in top_actors] for s in top_sectors]
    max_val = max((max(row) for row in matrix if row), default=0)
    return {"sectors": top_sectors, "actors": top_actors, "matrix": matrix, "max_val": max_val}


# ── v2 dependents (deferred cluster / IOC / reliability spread) ────────────


async def _get_critical_cves(session: AsyncSession, client_id: str) -> list[dict[str, Any]]:
    try:
        rows = await AsyncDashboardRepo(session).critical_cves(client_id=client_id, limit=20)
        return [
            {
                "cve_id": c.cve_id,
                "cve_score": c.cve_score,
                "cve_severity": c.cve_severity,
                "cisa_kev": c.cisa_kev,
                "tech": c.tech,
            }
            for c in rows
        ]
    except Exception:
        return []


async def _get_recent_clusters(session: AsyncSession, client_id: str) -> list[dict[str, Any]]:
    try:
        campaigns = await campaign_service.get_recent_campaigns(
            session, days=30, client_id=client_id, min_size=2
        )
        return [
            {
                "cluster_id": str(c.get("cluster_id", "")),
                "summary_title": c.get("summary_title") or "",
                "size": c.get("size") or 0,
                "threat_actors": c.get("dominant_tas") or [],
                "last_seen": c.get("last_seen") or "",
            }
            for c in campaigns[:10]
        ]
    except Exception:
        return []


async def _get_pending_fp_queue(session: AsyncSession) -> list[dict[str, Any]]:
    try:
        rows = await AsyncDashboardRepo(session).pending_fp_queue(limit=20)
        return [
            {
                "id": i.id,
                "value": i.value,
                "type": i.type,
                "last_seen": i.last_seen_at.isoformat(),
                "confidence_score": i.confidence_score,
            }
            for i in rows
        ]
    except Exception:
        return []


async def _get_source_reliability_spread(session: AsyncSession) -> dict[str, int]:
    from cti_api.services.source_score import get_source_reliability

    try:
        rows = await AsyncDashboardRepo(session).source_counts()
        spread: dict[str, int] = defaultdict(int)
        for source, count in rows:
            spread[get_source_reliability(source)] += count
        return dict(spread)
    except Exception:
        return {}


# ── v2 main ──────────────────────────────────────────────────────────────────


async def get_exec_dashboard_v2(
    session: AsyncSession,
    days: int = 90,
    incident_only: bool = True,
    confirmed_only: bool = False,
    client_id: str = "default",
    role: str = "analyst",
) -> dict[str, Any]:
    repo = AsyncDashboardRepo(session)
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=days)
    prev_cut = today - datetime.timedelta(days=days * 2)

    exclude = sorted(NON_INCIDENT_TYPES) if incident_only else None
    base: _DateFilters = {
        "posted_on_start": cutoff,
        "posted_on_end": None,
        "exclude_news_types": exclude,
        "confirmed_only": confirmed_only,
    }
    prev_base: _DateFilters = {
        "posted_on_start": prev_cut,
        "posted_on_end": cutoff,
        "exclude_news_types": exclude,
        "confirmed_only": confirmed_only,
    }

    base_dash = await get_exec_dashboard(
        session, days=days, incident_only=incident_only, confirmed_only=confirmed_only
    )
    prev_ta_names = await repo.distinct_threat_actors(**prev_base)

    cve_v2_raw = await repo.cve_tech_severity_breakdown(limit=10, with_extras=True)
    cve_kpis = await repo.cve_kpi_counts()

    spike_data = await spike_service.get_spikes(
        session,
        lookback_days=max(days, 30),
        z_threshold=1.5,
        exclude_news_types=exclude,
        confirmed_only=confirmed_only,
    )

    victim_country_raw = await repo.monthly_country_counts(role="victim", **base)
    ttp_raw = await repo.ttp_counts(limit=15, **base)
    ta_monthly_raw = await repo.monthly_ta_counts(**base)
    cooccur_map = await repo.article_industries_for_cooccurrence(**base)
    newstype_monthly_raw = await repo.monthly_newstype_counts(**base)

    months = base_dash["months"]
    top_sectors = base_dash["top_sectors"]
    top_actor_names = [r["name"] for r in base_dash["ta_leaderboard"]][:8]
    top_actor_names_for_conf = [r["name"] for r in base_dash["ta_leaderboard"]]

    sector_actor_raw = await repo.sector_actor_counts(
        sectors=top_sectors[:8], actors=top_actor_names, **base
    )
    ta_conf_raw = await repo.ta_confidence_raw(
        posted_on_start=cutoff, actors=top_actor_names_for_conf
    )
    non_incident_by_actor = await repo.non_incident_counts_by_actor(
        posted_on_start=cutoff,
        actors=top_actor_names_for_conf,
        non_incident_types=sorted(NON_INCIDENT_TYPES),
    )
    confirmed_total, confirmed_yes = await repo.confirmed_incident_rate_raw(**base)

    # ── Tier 1 ──
    cve_exposure_v2 = cve_v2_raw
    sector_risk_scores = _compute_sector_risk_scores(base_dash["sector_trend"])
    industry_spikes = spike_data.get("industries", [])[:6]

    # ── Tier 2 ──
    vc_map: dict[str, dict[str, int]] = {}
    for country, mo, cnt in victim_country_raw:
        vc_map.setdefault(country, {})[mo] = cnt
    vc_totals = {c: sum(v.values()) for c, v in vc_map.items()}
    top_vc = sorted(vc_totals, key=lambda x: -vc_totals[x])[:8]
    victim_country_trend = [
        {"country": c, "data": [vc_map[c].get(m, 0) for m in months]} for c in top_vc
    ]

    top_ttps = [{"id": tid, "name": name or tid, "count": cnt} for tid, name, cnt in ttp_raw]
    ta_velocity = _compute_ta_velocity(ta_monthly_raw, months)
    sector_cooccurrence = _compute_sector_cooccurrence(cooccur_map)
    newstype_trend = _build_newstype_trend(newstype_monthly_raw, months)
    sector_actor_matrix = _build_sector_actor_matrix(
        sector_actor_raw, top_sectors[:8], top_actor_names
    )

    # ── Tier 3 ──
    ta_confidence: dict[str, int] = {}
    for actor, total, confirmed_count, has_field_count in ta_conf_raw:
        if not total:
            continue
        if has_field_count > 0:
            ta_confidence[actor] = round((confirmed_count / total) * 100)
        else:
            non_incident = non_incident_by_actor.get(actor, 0)
            ta_confidence[actor] = round(((total - non_incident) / total) * 100)

    confirmed_incident_rate = (
        round((confirmed_yes / confirmed_total) * 100) if confirmed_total else None
    )

    view_config = build_view_config(role)
    sections = view_config["sections"]

    critical_cves = (
        await _get_critical_cves(session, client_id) if sections.get("critical_cve_feed") else []
    )
    recent_clusters_summary = (
        await _get_recent_clusters(session, client_id) if sections.get("cluster_list") else []
    )
    pending_fp_queue = (
        await _get_pending_fp_queue(session) if sections.get("fp_feedback_queue") else []
    )
    source_reliability_spread = (
        await _get_source_reliability_spread(session)
        if sections.get("source_reliability_spread")
        else {}
    )

    return {
        **base_dash,
        "prev_ta_names": prev_ta_names,
        "sector_risk_scores": sector_risk_scores,
        "cve_exposure_v2": cve_exposure_v2,
        "cve_kpis": cve_kpis,
        "industry_spikes": industry_spikes,
        "victim_country_trend": victim_country_trend,
        "top_ttps": top_ttps,
        "ta_velocity": ta_velocity,
        "sector_cooccurrence": sector_cooccurrence,
        "newstype_trend": newstype_trend,
        "sector_actor_matrix": sector_actor_matrix,
        "ta_confidence": ta_confidence,
        "confirmed_incident_rate": confirmed_incident_rate,
        "view_config": view_config,
        "critical_cves": critical_cves,
        "recent_clusters_summary": recent_clusters_summary,
        "pending_fp_queue": pending_fp_queue,
        "source_reliability_spread": source_reliability_spread,
    }
