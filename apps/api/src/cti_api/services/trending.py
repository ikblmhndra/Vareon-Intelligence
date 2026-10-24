"""Trending actor + TTP: entitas yang NAIK dibanding window sebelumnya
dengan panjang sama (mis. 7 hari terakhir vs 7 hari sebelumnya). Dipakai
endpoint dashboard `/api/dashboard/trending` dan (nanti) topik newsroom,
makanya logika ranking dipisah murni (`rank_trends`) dari query.

Beda dari `spike` (z-score vs baseline panjang): di sini yang dicari
kenaikan absolut yang gampang dibaca analis. `change_pct` sengaja `None`
kalau baseline < 3 -- "+400%" dari 1 ke 5 menyesatkan; entitas baru
(baseline 0) ditandai `is_new`. Window sebelumnya yang hari berisinya kurang dari
`PREV_MIN_DAY_COVERAGE` (aturan yang sama dengan KPI dashboard/Exec) membuat
`baseline_reliable=False`: item tetap diurutkan, tapi `is_new`/`change_pct` dikosongkan,
karena "T1190 129 vs 1" di instance yang baru jalan bukan kenaikan (audit UI U4). Cache
in-memory 900 detik, pola yang sama dengan `article_dashboard`/`spike`."""

from __future__ import annotations

import datetime
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services.exec_dashboard import PREV_MIN_DAY_COVERAGE

_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_CACHE_TTL = 900
_MIN_BASELINE_FOR_PCT = 3
# Sparkline cukup 31 titik terakhir: window panjang (mis. 3650 hari dari newsroom
# "semua waktu" yang di-clamp) tetap dihitung penuh, tapi `daily` tidak dikirim ribuan elemen.
_MAX_DAILY_BUCKETS = 31

TrendKey = tuple[str, str, str | None]


@dataclass(frozen=True)
class TrendItem:
    kind: Literal["actor", "ttp"]
    name: str
    ttp_id: str | None
    count: int
    prev_count: int
    change_pct: int | None
    is_new: bool
    daily: list[int]


def rank_trends(
    current: Mapping[TrendKey, list[int]],
    previous: Mapping[TrendKey, int],
    *,
    min_count: int = 3,
    limit: int = 10,
) -> list[TrendItem]:
    """Urut kenaikan absolut (count - prev_count) desc, lalu count desc,
    lalu nama. Yang di bawah `min_count` atau tidak naik dibuang."""
    items: list[TrendItem] = []
    for (kind, name, ttp_id), daily in current.items():
        count = sum(daily)
        prev = previous.get((kind, name, ttp_id), 0)
        if count < min_count or count - prev <= 0:
            continue
        pct = round((count - prev) * 100 / prev) if prev >= _MIN_BASELINE_FOR_PCT else None
        items.append(
            TrendItem(
                kind="ttp" if kind == "ttp" else "actor",
                name=name,
                ttp_id=ttp_id,
                count=count,
                prev_count=prev,
                change_pct=pct,
                is_new=prev == 0,
                daily=list(daily),
            )
        )
    items.sort(key=lambda i: (-(i.count - i.prev_count), -i.count, i.name))
    return items[:limit]


def _split_ttp(entity: str) -> tuple[str, str]:
    ttp_id, _, ttp_name = entity.partition("|")
    return ttp_id, ttp_name


async def get_trending(
    session: AsyncSession,
    *,
    days: int | None,
    countries: Sequence[str] | None = None,
    news_types: Sequence[str] | None = None,
    search: str | None = None,
    confirmed_only: bool = False,
    limit: int = 10,
) -> dict[str, Any]:
    cache_key = (
        f"{days}|{sorted(countries or [])}|{sorted(news_types or [])}|{search}"
        f"|{confirmed_only}|{limit}|{datetime.date.today().isoformat()}"
    )
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if cached is not None and now - cached[1] < _CACHE_TTL:
        return cached[0]

    # "Semua waktu" tidak punya arti buat tren: jatuh ke 7 hari vs 7 hari.
    window = days if days is not None else 7
    today = datetime.date.today()
    # Window sama panjang: current = `window` hari berakhir hari ini
    # (inklusif), previous = `window` hari persis sebelumnya.
    cur_start = today - datetime.timedelta(days=window - 1)
    prev_start = cur_start - datetime.timedelta(days=window)
    filters: dict[str, Any] = {
        "countries": countries,
        "news_types": news_types,
        "search": search,
        "confirmed_only": confirmed_only,
    }

    repo = AsyncDashboardRepo(session)
    current: dict[TrendKey, list[int]] = {}
    previous: dict[TrendKey, int] = {}
    # Sekuensial: satu AsyncSession tidak aman dipakai concurrent.
    for dimension, kind in (("threat_actor", "actor"), ("ttp", "ttp")):
        cur_rows = await repo.daily_entity_counts(
            dimension=dimension,
            posted_on_start=cur_start,
            posted_on_end=today + datetime.timedelta(days=1),
            **filters,
        )
        prev_rows = await repo.daily_entity_counts(
            dimension=dimension, posted_on_start=prev_start, posted_on_end=cur_start, **filters
        )
        # Repo sudah group per `ttp_id`, tapi nama fallback (`min(ttp_name)` kalau ID tidak
        # ada di katalog ATT&CK) dihitung per hari, jadi bisa beda antar-hari. Satu nama per
        # ID (yang terkecil) supaya satu technique tetap satu item (QA BUG-04).
        ttp_names: dict[str, str] = {}
        if kind == "ttp":
            for _day, entity, _cnt in (*cur_rows, *prev_rows):
                tid, tname = _split_ttp(entity)
                ttp_names[tid] = min(ttp_names.get(tid, tname), tname)

        def _key(entity: str, kind: str = kind, names: dict[str, str] = ttp_names) -> TrendKey:
            if kind == "actor":
                return (kind, entity, None)
            tid, _ = _split_ttp(entity)
            return (kind, names[tid], tid)

        for day, entity, cnt in cur_rows:
            buckets = current.setdefault(_key(entity), [0] * window)
            buckets[(day - cur_start).days] += cnt
        for _day, entity, cnt in prev_rows:
            key = _key(entity)
            previous[key] = previous.get(key, 0) + cnt

    baseline_reliable = (
        await repo.distinct_day_count(posted_on_start=prev_start, posted_on_end=cur_start)
        >= window * PREV_MIN_DAY_COVERAGE
    )
    ranked = rank_trends(current, previous, limit=limit)
    if not baseline_reliable:
        ranked = [replace(i, is_new=False, change_pct=None) for i in ranked]
        label = f"{window} hari terakhir (pembanding belum cukup data)"
    else:
        label = f"{window} hari terakhir vs {window} hari sebelumnya"
    result = {
        "items": [{**asdict(i), "daily": i.daily[-_MAX_DAILY_BUCKETS:]} for i in ranked],
        "window_days": window,
        "window_label": label,
        "baseline_reliable": baseline_reliable,
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _CACHE[cache_key] = (result, now)
    return result
