"""Port `ScraperNewsWeb/app/services/spike_service.py`. Fase 7.3 (router
`intelligence`, Bagian 5). Deteksi lonjakan (z-score) per TA/negara/
industri + total harian, window terakhir (7 hari) vs baseline (sisa
`lookback_days`). Cache in-memory TTL 900 detik, port apa adanya (bukan
Redis -- kode lama juga cuma dict proses, gak lintas worker)."""

from __future__ import annotations

import datetime
import statistics
import time
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from cti_core.db.repositories.entity import (
    ACTOR,
    COUNTRY,
    SECTOR,
    entity_ids_by_external_id_async,
    name_keys_async,
)
from sqlalchemy.ext.asyncio import AsyncSession

_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_CACHE_TTL = 900


async def get_spikes(
    session: AsyncSession,
    lookback_days: int = 30,
    z_threshold: float = 2.0,
    *,
    exclude_news_types: list[str] | None = None,
    confirmed_only: bool = False,
) -> dict[str, Any]:
    cache_key = f"{lookback_days}|{z_threshold}|{sorted(exclude_news_types or [])}|{confirmed_only}"
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if cached is not None:
        data, ts = cached
        if now - ts < _CACHE_TTL:
            return data

    result = await _compute_spikes(
        session, lookback_days, z_threshold, exclude_news_types, confirmed_only
    )
    _CACHE[cache_key] = (result, now)
    return result


async def _compute_spikes(
    session: AsyncSession,
    lookback_days: int,
    z_threshold: float,
    exclude_news_types: list[str] | None,
    confirmed_only: bool,
) -> dict[str, Any]:
    repo = AsyncDashboardRepo(session)
    cutoff = datetime.date.today() - datetime.timedelta(days=lookback_days)
    recent_cutoff = datetime.date.today() - datetime.timedelta(days=7)

    # Sekuensial, bukan asyncio.gather -- satu AsyncSession gak aman
    # dipakai concurrent (beda dari `$facet` Mongo lama yang emang satu
    # pipeline). Sama constraint yang udah didokumentasikan di
    # `AsyncPIRRepo.list_pirs()`/`pkg_vuln.scan_all_packages()`.
    by_actor = await repo.daily_entity_counts(
        dimension="threat_actor",
        posted_on_start=cutoff,
        exclude_news_types=exclude_news_types,
        confirmed_only=confirmed_only,
    )
    by_country = await repo.daily_entity_counts(
        dimension="country",
        posted_on_start=cutoff,
        exclude_news_types=exclude_news_types,
        confirmed_only=confirmed_only,
    )
    by_industry = await repo.daily_entity_counts(
        dimension="industry",
        posted_on_start=cutoff,
        exclude_news_types=exclude_news_types,
        confirmed_only=confirmed_only,
    )
    daily_total = await repo.daily_totals(
        posted_on_start=cutoff,
        exclude_news_types=exclude_news_types,
        confirmed_only=confirmed_only,
    )

    actor_spikes = _detect_entity_spikes(
        by_actor, recent_cutoff, z_threshold, baseline_start=cutoff
    )
    country_spikes = _detect_entity_spikes(
        by_country, recent_cutoff, z_threshold, baseline_start=cutoff
    )
    industry_spikes = _detect_entity_spikes(
        by_industry, recent_cutoff, z_threshold, baseline_start=cutoff
    )
    # `entity_id` dicari sesudah deteksi (satu query per dimensi), hanya untuk entri yang lolos.
    actor_keys = await name_keys_async(session, ACTOR, [str(s["entity"]) for s in actor_spikes])
    industry_keys = await name_keys_async(
        session, SECTOR, [str(s["entity"]) for s in industry_spikes]
    )
    country_ids = await entity_ids_by_external_id_async(
        session, COUNTRY, [str(s["entity"]) for s in country_spikes]
    )
    for sp in actor_spikes:
        sp["entity_id"] = actor_keys.entity_id(str(sp["entity"]))
    for sp in industry_spikes:
        sp["entity_id"] = industry_keys.entity_id(str(sp["entity"]))
    for sp in country_spikes:
        sp["entity_id"] = country_ids.get(str(sp["entity"]))

    today = datetime.date.today()
    axis = _date_axis(cutoff, today)
    totals_by_date = dict(daily_total)
    daily = {
        "dates": [d.isoformat() for d in axis],
        "threat_actors": _daily_series(
            by_actor, (str(s["entity"]) for s in actor_spikes), cutoff, today
        ),
        "countries": _daily_series(
            by_country, (str(s["entity"]) for s in country_spikes), cutoff, today
        ),
        "industries": _daily_series(
            by_industry, (str(s["entity"]) for s in industry_spikes), cutoff, today
        ),
        "overall": [totals_by_date.get(d, 0) for d in axis],
    }

    return {
        "threat_actors": actor_spikes,
        "countries": country_spikes,
        "industries": industry_spikes,
        "overall": _detect_overall_spikes(
            daily_total, recent_cutoff, z_threshold, baseline_start=cutoff
        ),
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "parameters": {
            "lookback_days": lookback_days,
            "z_threshold": z_threshold,
            "recent_window": "last 7 days",
        },
        "daily": daily,
    }


def _date_axis(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    """Sumbu tanggal inklusif `start..end`, menaik."""
    return [start + datetime.timedelta(days=i) for i in range((end - start).days + 1)]


def _daily_series(
    raw: list[tuple[datetime.date, str, int]],
    entities: Iterable[str],
    start: datetime.date,
    end: datetime.date,
) -> dict[str, list[int]]:
    """Hitungan harian per entitas, zero-filled di sumbu `start..end`. Hanya `entities`
    yang dimuat (entitas yang masuk daftar spike), bukan seluruh `raw`, supaya respons kecil."""
    names = list(dict.fromkeys(entities))
    wanted = set(names)
    series = _build_series([r for r in raw if r[1] in wanted])
    axis = _date_axis(start, end)
    return {e: [series.get(e, {}).get(d, 0) for d in axis] for e in names}


def _build_series(
    raw: list[tuple[datetime.date, str, int]],
) -> dict[str, dict[datetime.date, int]]:
    series: dict[str, dict[datetime.date, int]] = defaultdict(dict)
    for date, entity, count in raw:
        series[entity][date] = count
    return series


def _baseline_days(
    baseline_start: datetime.date, recent_cutoff: datetime.date
) -> list[datetime.date]:
    """Hari baseline `baseline_start..recent_cutoff-1`, inklusif."""
    return _date_axis(baseline_start, recent_cutoff - datetime.timedelta(days=1))


def _detect_entity_spikes(
    raw: list[tuple[datetime.date, str, int]],
    recent_cutoff: datetime.date,
    z_threshold: float,
    *,
    baseline_start: datetime.date,
) -> list[dict[str, Any]]:
    """Baseline = SEMUA hari `baseline_start..recent_cutoff-1`, hari tanpa artikel = 0 (0.8.15).

    Dulu mean/std hanya dari hari yang ada artikelnya: garis baseline di kartu Early Warning jadi
    lebih tinggi daripada batang deret `daily` (yang mengisi 0), dan entitas yang jarang muncul
    mendapat z-score terlalu kecil. Syarat "minimal 5 hari baseline" tetap berarti 5 hari yang ADA
    artikelnya (kalau dihitung dengan hari nol, syarat itu selalu lolos). Filter lama `mean < 0.5`
    dibuang: dengan nilai harian >= 1 ia tidak pernah aktif, dan dengan hari nol ia justru akan
    membuang entitas jarang yang memang ingin terdeteksi."""
    series = _build_series(raw)
    baseline_days = _baseline_days(baseline_start, recent_cutoff)
    spikes = []

    for entity, daily in series.items():
        baseline_vals = [daily.get(d, 0) for d in baseline_days]
        recent_dates = sorted(d for d in daily if d >= recent_cutoff)

        if sum(1 for v in baseline_vals if v > 0) < 5:
            continue

        mean = statistics.mean(baseline_vals)

        try:
            std = statistics.stdev(baseline_vals)
        except statistics.StatisticsError:
            std = 0.0
        std = std or 0.5

        for date in recent_dates:
            count = daily[date]
            z_score = (count - mean) / std
            if z_score >= z_threshold:
                spikes.append(
                    {
                        "entity": entity,
                        "date": date.isoformat(),
                        "count": count,
                        "baseline_mean": round(mean, 2),
                        "z_score": round(z_score, 2),
                        "severity": "high" if z_score >= 3.0 else "medium",
                    }
                )

    spikes.sort(key=lambda x: float(x["z_score"]), reverse=True)  # type: ignore[arg-type]
    return spikes[:20]


def _detect_overall_spikes(
    daily_total: list[tuple[datetime.date, int]],
    recent_cutoff: datetime.date,
    z_threshold: float,
    *,
    baseline_start: datetime.date,
) -> list[dict[str, Any]]:
    """Sama dengan `_detect_entity_spikes`: hari baseline tanpa artikel dihitung 0 (0.8.15)."""
    by_date = dict(daily_total)
    baseline_vals = [by_date.get(d, 0) for d in _baseline_days(baseline_start, recent_cutoff)]
    recent = [(date, count) for date, count in daily_total if date >= recent_cutoff]

    if sum(1 for v in baseline_vals if v > 0) < 5:
        return []

    mean = statistics.mean(baseline_vals)
    try:
        std = statistics.stdev(baseline_vals)
    except statistics.StatisticsError:
        std = 0.0
    std = std or 1.0

    surges = []
    for date, count in recent:
        z = (count - mean) / std
        if z >= z_threshold:
            surges.append(
                {
                    "date": date.isoformat(),
                    "count": count,
                    "baseline_mean": round(mean, 2),
                    "z_score": round(z, 2),
                    "severity": "high" if z >= 3.0 else "medium",
                }
            )
    return surges
