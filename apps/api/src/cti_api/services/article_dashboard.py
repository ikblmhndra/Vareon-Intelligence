"""Port `ScraperNewsWeb/app/services/article_service.py`'s
`get_dashboard_stats()`/`_fetch_dashboard_stats()`. Fase 7.4 Grup D --
endpoint `/api/dashboard` yang ketinggalan pas Fase 7.3 karena blocker
normalisasi negara (SEKARANG udah kejadian di enrichment, Fase 2/5,
lihat docstring `AsyncDashboardRepo` bagian "article dashboard").

Cache TTL module-level 900 detik (15 menit), pola sama kayak
`spike.py`/`risk_matrix.py`/`fp_analytics.py` -- per-proses uvicorn.

Dashboard informativeness: `days` (periode + pembanding periode sebelumnya,
pola `exec_dashboard.get_exec_dashboard`), `incident_only` (buang
`NON_INCIDENT_TYPES`), `confirmed_incidents`, `coverage` (penyebut chart), dan
industri "General" dipisah dari `top_industries` -- di prod 62% artikel
berlabel "General", jadi tanpa dipisah bar teratas selalu "General"."""

from __future__ import annotations

import datetime
import time
from typing import Any

from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services.exec_dashboard import NON_INCIDENT_TYPES, UNSPECIFIED_INDUSTRY

_dashboard_cache: dict[str, tuple[dict[str, Any], float]] = {}
_CACHE_TTL = 900.0


async def get_dashboard_stats(
    session: AsyncSession,
    *,
    posted_on_start: datetime.date | None = None,
    posted_on_end: datetime.date | None = None,
    days: int | None = None,
    incident_only: bool = False,
) -> dict[str, Any]:
    """`days` menang atas `posted_on_start`/`posted_on_end` (jendela = `days` hari
    terakhir sampai hari ini) dan mengaktifkan field pembanding `prev_*`."""
    start_key = posted_on_start.isoformat() if posted_on_start else ""
    end_key = posted_on_end.isoformat() if posted_on_end else ""
    # `date.today()` di key: cache gak boleh basi lewat tengah malam kalau `days` dipakai.
    cache_key = f"{start_key}|{end_key}|{days}|{incident_only}|{datetime.date.today().isoformat()}"
    now = time.monotonic()
    cached = _dashboard_cache.get(cache_key)
    if cached is not None and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    result = await _fetch_dashboard_stats(
        session,
        posted_on_start=posted_on_start,
        posted_on_end=posted_on_end,
        days=days,
        incident_only=incident_only,
    )
    _dashboard_cache[cache_key] = (result, now)
    return result


async def _fetch_dashboard_stats(
    session: AsyncSession,
    *,
    posted_on_start: datetime.date | None,
    posted_on_end: datetime.date | None,
    days: int | None,
    incident_only: bool,
) -> dict[str, Any]:
    repo = AsyncDashboardRepo(session)
    today = datetime.date.today()
    if days is not None:
        posted_on_start = today - datetime.timedelta(days=days)
        posted_on_end = None
    filters: dict[str, Any] = {
        "posted_on_start": posted_on_start,
        "posted_on_end": posted_on_end,
        "exclude_news_types": sorted(NON_INCIDENT_TYPES) if incident_only else None,
    }

    # Sekuensial (bukan `asyncio.gather`) -- satu `AsyncSession` gak aman
    # dipakai concurrent, constraint yang udah didokumentasikan berkali-
    # kali sesi ini (`exec_dashboard.py`, dst).
    total = await repo.count_articles(**filters)
    confirmed = await repo.count_articles(confirmed_only=True, **filters)
    total_sources = await repo.distinct_source_count(**filters)
    total_countries = await repo.unique_country_count(**filters)
    total_threat_actors = await repo.unique_threat_actor_count(**filters)
    country_counts = await repo.top_countries(limit=300, **filters)
    top_countries = country_counts[:10]
    top_sources = await repo.top_sources(limit=10, **filters)
    top_actors = await repo.top_threat_actors(limit=10, **filters)
    # 30 > 10 supaya "General" (hampir pasti teratas) terpisah tanpa menggeser 10 sektor spesifik.
    industries = await repo.top_industries(limit=30, **filters)
    industry_unspecified = sum(cnt for i, cnt in industries if i == UNSPECIFIED_INDUSTRY)
    top_industries = [(i, cnt) for i, cnt in industries if i != UNSPECIFIED_INDUSTRY][:10]
    top_ttps = await repo.ttp_counts(limit=10, **filters)
    by_type = await repo.news_type_breakdown(**filters)
    timeline = await repo.article_timeline(**filters)
    coverage = await repo.coverage_counts(**filters)

    prev_total: int | None = None
    prev_confirmed: int | None = None
    if days is not None:
        # Rentang [today-2d, today-d) -- ujung akhir eksklusif di repo, jadi gak tumpang
        # tindih dengan jendela sekarang yang mulai di `today-d` (inklusif).
        prev_filters: dict[str, Any] = {
            **filters,
            "posted_on_start": today - datetime.timedelta(days=days * 2),
            "posted_on_end": posted_on_start,
        }
        prev_total = await repo.count_articles(**prev_filters)
        prev_confirmed = await repo.count_articles(confirmed_only=True, **prev_filters)

    return {
        "total_articles": total,
        "confirmed_incidents": confirmed,
        "prev_total_articles": prev_total,
        "prev_confirmed_incidents": prev_confirmed,
        "total_sources": total_sources,
        "total_countries": total_countries,
        "total_threat_actors": total_threat_actors,
        "top_countries": [{"name": c, "count": cnt} for c, cnt in top_countries],
        "country_counts": [{"name": c, "count": cnt} for c, cnt in country_counts],
        "top_sources": [{"name": s, "count": cnt} for s, cnt in top_sources],
        "top_threat_actors": [{"name": a, "count": cnt} for a, cnt in top_actors],
        "top_industries": [{"name": i, "count": cnt} for i, cnt in top_industries],
        "industry_unspecified": industry_unspecified,
        "top_ttps": [{"name": f"{tid} — {tname}", "count": cnt} for tid, tname, cnt in top_ttps],
        "by_news_type": [{"name": nt, "count": cnt} for nt, cnt in by_type if nt],
        "timeline": [{"date": d.isoformat(), "count": cnt} for d, cnt in timeline],
        "coverage": coverage,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
