"""Port `ScraperNewsWeb/app/services/risk_matrix_service.py`. Fase 7.3
(router `intelligence`, Bagian 5). Matriks risiko industri x negara,
skor 0-100 dari jumlah TA unik/TTP unik/volume artikel periode berjalan,
dibandingin periode sebelumnya buat tren (naik/turun/stabil).

**Bug ketemu, DIPERBAIKI (bukan asimetri desain):** kode lama baca
`doc.get("attack_techniques")` buat komponen TTP formula skor -- field
itu TIDAK PERNAH ada di dokumen artikel Mongo manapun (grep lintas
`ScraperNews`/`ScraperNewsWeb`: field ini cuma dipakai `ta_profile_
service.py`/`attack_sync_service.py`/dst buat konteks LAIN sama sekali,
bukan field artikel). TTP artikel yang beneran ada namanya `ttps`. Efek
di kode lama: komponen `unique_ttps * 2` di formula skor SELALU 0,
diem-diem mati -- bukan keputusan desain, ketauan typo/field salah pas
baca detail buat porting. Di sini pakai `ttps` (field asli, ternormalisasi
mention teknik) supaya komponen TTP skor beneran jalan -- perubahan
perilaku yang disengaja & didokumentasikan, bukan silent fix."""

from __future__ import annotations

import datetime
import time
from collections import defaultdict
from typing import Any

from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from sqlalchemy.ext.asyncio import AsyncSession

_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_CACHE_TTL = 900


async def get_risk_matrix(
    session: AsyncSession, days: int = 30, compare_days: int = 30
) -> dict[str, Any]:
    cache_key = f"{days}|{compare_days}"
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if cached is not None:
        data, ts = cached
        if now - ts < _CACHE_TTL:
            return data

    result = await _compute_risk_matrix(session, days, compare_days)
    _CACHE[cache_key] = (result, now)
    return result


async def _compute_risk_matrix(
    session: AsyncSession, days: int, compare_days: int
) -> dict[str, Any]:
    repo = AsyncDashboardRepo(session)
    today = datetime.date.today()
    current_start = today - datetime.timedelta(days=days)
    prev_start = today - datetime.timedelta(days=days + compare_days)
    prev_end = current_start

    rows = await repo.risk_matrix_rows(posted_on_start=prev_start)

    cell_current: dict[tuple[str, str], list[dict[str, list[str]]]] = defaultdict(list)
    cell_previous: dict[tuple[str, str], list[dict[str, list[str]]]] = defaultdict(list)

    for row in rows:
        posted_on = row["posted_on"]
        industries = row["industries"]
        countries = row["countries"]
        tas = row["threat_actors"]
        ttps = row["ttps"]

        if not industries or not countries or posted_on is None:
            continue

        is_current = posted_on >= current_start
        is_prev = prev_start <= posted_on < prev_end

        for industry in industries:
            for country in countries:
                key = (industry, country)
                if is_current:
                    cell_current[key].append({"tas": tas, "ttps": ttps})
                elif is_prev:
                    cell_previous[key].append({"tas": tas, "ttps": ttps})

    all_keys = set(cell_current.keys()) | set(cell_previous.keys())

    raw_scores: dict[tuple[str, str], float] = {}
    for key in all_keys:
        curr_docs = cell_current.get(key, [])
        if len(curr_docs) < 2:
            continue
        unique_tas = len({t for d in curr_docs for t in d["tas"]})
        unique_ttps = len({t for d in curr_docs for t in d["ttps"]})
        raw_scores[key] = unique_tas * 3 + unique_ttps * 2 + len(curr_docs) * 1

    max_raw = max(raw_scores.values(), default=1) or 1

    matrix: list[dict[str, Any]] = []
    for key, raw in raw_scores.items():
        industry, country = key
        curr_docs = cell_current.get(key, [])
        prev_docs = cell_previous.get(key, [])
        current_count = len(curr_docs)
        previous_count = len(prev_docs)

        if current_count > previous_count * 1.2:
            trend = "↑"  # naik
        elif previous_count > 0 and current_count < previous_count * 0.8:
            trend = "↓"  # turun
        else:
            trend = "→"  # stabil

        risk_score = round(raw / max_raw * 100)

        ta_counts: dict[str, int] = defaultdict(int)
        for d in curr_docs:
            for ta in d["tas"]:
                ta_counts[ta] += 1
        top_actors = [ta for ta, _ in sorted(ta_counts.items(), key=lambda x: -x[1])[:3]]

        matrix.append(
            {
                "industry": industry,
                "country": country,
                "risk_score": risk_score,
                "trend": trend,
                "current_count": current_count,
                "previous_count": previous_count,
                "top_actors": top_actors,
            }
        )

    matrix.sort(key=lambda x: -x["risk_score"])

    industries_all = sorted({str(r["industry"]) for r in matrix})
    countries_all = sorted({str(r["country"]) for r in matrix})

    return {
        "matrix": matrix,
        "industries": industries_all,
        "countries": countries_all,
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
