"""Trending actor + TTP: entitas yang NAIK dibanding window sebelumnya
dengan panjang sama (mis. 7 hari terakhir vs 7 hari sebelumnya). Dipakai
endpoint dashboard `/api/dashboard/trending` dan (nanti) topik newsroom,
makanya logika ranking dipisah murni (`rank_trends`) dari query.

Beda dari `spike` (z-score vs baseline panjang): di sini yang dicari
kenaikan absolut yang gampang dibaca analis. `change_pct` sengaja `None`
kalau baseline < 3 -- "+400%" dari 1 ke 5 menyesatkan; entitas baru
(baseline 0) ditandai `is_new`. Cache in-memory 900 detik, pola yang sama
dengan `article_dashboard`/`spike`."""

from __future__ import annotations

import datetime
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from sqlalchemy.ext.asyncio import AsyncSession

_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_CACHE_TTL = 900
_MIN_BASELINE_FOR_PCT = 3

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
    limit: int = 10,
) -> dict[str, Any]:
    cache_key = (
        f"{days}|{sorted(countries or [])}|{sorted(news_types or [])}|{search}|{limit}"
        f"|{datetime.date.today().isoformat()}"
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
    filters: dict[str, Any] = {"countries": countries, "news_types": news_types, "search": search}

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
        for day, entity, cnt in cur_rows:
            name, ttp_id = (entity, None) if kind == "actor" else _split_ttp(entity)[::-1]
            buckets = current.setdefault((kind, name, ttp_id), [0] * window)
            buckets[(day - cur_start).days] += cnt
        prev_rows = await repo.daily_entity_counts(
            dimension=dimension, posted_on_start=prev_start, posted_on_end=cur_start, **filters
        )
        for _day, entity, cnt in prev_rows:
            name, ttp_id = (entity, None) if kind == "actor" else _split_ttp(entity)[::-1]
            key = (kind, name, ttp_id)
            previous[key] = previous.get(key, 0) + cnt

    label = f"{window} hari terakhir vs {window} hari sebelumnya"
    result = {
        "items": [asdict(i) for i in rank_trends(current, previous, limit=limit)],
        "window_days": window,
        "window_label": label,
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _CACHE[cache_key] = (result, now)
    return result
