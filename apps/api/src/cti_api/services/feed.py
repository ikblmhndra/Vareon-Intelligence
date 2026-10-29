"""Query feed indikator bersama untuk REST `/api/v2/indicators` dan server TAXII (P7b 4.2).

Satu-satunya jalur baca feed mesin, supaya TLP, settle lag, dan keyset paging benar di satu tempat.

Settle lag: `feed_changed_at` diisi `clock_timestamp()` = waktu statement tulis, bukan waktu commit
(dan bukan awal transaksi, yang bisa berumur menit di pipeline enrich). Selisih tulis -> commit
bisa membuat baris muncul terlambat di bawah kursor klien, jadi baris yang lebih baru dari
`FEED_SETTLE_SECONDS` tidak dikembalikan. Persist adalah langkah terakhir sebelum commit, jadi 60 s
cukup; jika kelak ada penulis indikator yang menunda commit lebih lama, naikkan konstanta ini.
Lookup per id (`stix_ids`) tidak dikenai settle lag."""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime

from cti_core.db.models.indicator import Indicator
from cti_core.indicator.marking import tlp_allowed
from sqlalchemy import func, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

FEED_SETTLE_SECONDS = 60


def encode_cursor(changed_at: datetime, indicator_id: int) -> str:
    raw = f"{changed_at.astimezone(UTC).isoformat()}|{indicator_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    """`ValueError` untuk apa pun yang cacat, termasuk cap waktu tanpa zona."""
    try:
        ts_raw, id_raw = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        changed_at = datetime.fromisoformat(ts_raw)
        indicator_id = int(id_raw)
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise ValueError("kursor tidak valid") from exc
    if changed_at.tzinfo is None:
        raise ValueError("kursor tidak valid: waktu tanpa zona")
    if not 1 <= indicator_id <= 2**63 - 1:  # di luar bigint Postgres -> 500 di query
        raise ValueError("kursor tidak valid: id di luar rentang")
    try:
        changed_at = changed_at.astimezone(UTC)  # nilai ekstrem (0001-01-01+01:00) meluap
    except OverflowError as exc:
        raise ValueError("kursor tidak valid: waktu di luar rentang") from exc
    return changed_at, indicator_id


@dataclass
class FeedPage:
    items: list[Indicator]
    next_cursor: str | None


async def feed_page(
    session: AsyncSession,
    *,
    max_tlp: str,
    limit: int,
    states: Collection[str] | None = None,
    types: Collection[str] | None = None,
    changed_after: datetime | None = None,
    after: tuple[datetime, int] | None = None,
    stix_ids: Collection[uuid.UUID] | None = None,
) -> FeedPage:
    """`states=None` berarti semua state. Urut `(feed_changed_at, id)`; `next_cursor` = kursor baris
    terakhir yang dikembalikan, hanya bila masih ada sisa."""
    stmt = (
        select(Indicator)
        .where(
            Indicator.tlp.in_(tlp_allowed(max_tlp)),
        )
        # Pemanggil (serializer REST v2, indicator_to_stix) hanya memakai `tags`.
        .options(
            selectinload(Indicator.tags),
            noload(Indicator.sources),
            noload(Indicator.threat_actors),
            noload(Indicator.feedback),
        )
        .order_by(Indicator.feed_changed_at, Indicator.id)
        .limit(limit + 1)
    )
    if states is not None:
        stmt = stmt.where(Indicator.state.in_(list(states)))
    if types is not None:
        stmt = stmt.where(Indicator.type.in_(list(types)))
    if changed_after is not None:
        stmt = stmt.where(Indicator.feed_changed_at > literal(changed_after))
    if after is not None:
        stmt = stmt.where(
            tuple_(Indicator.feed_changed_at, Indicator.id)
            > tuple_(literal(after[0]), literal(after[1]))
        )
    if stix_ids is not None:
        stmt = stmt.where(Indicator.stix_id.in_(list(stix_ids)))
    else:  # lookup per id tidak dikenai settle lag
        stmt = stmt.where(
            Indicator.feed_changed_at
            <= func.now() - func.make_interval(0, 0, 0, 0, 0, 0, FEED_SETTLE_SECONDS)
        )

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    items = rows[:limit]
    cursor = encode_cursor(items[-1].feed_changed_at, items[-1].id) if has_more else None
    return FeedPage(items=items, next_cursor=cursor)
