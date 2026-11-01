"""Query feed indikator bersama untuk REST `/api/v2/indicators` dan server TAXII (P7b 4.2).

Satu-satunya jalur baca feed mesin, supaya TLP, settle lag, dan keyset paging benar di satu tempat.

Settle lag: `feed_changed_at` diisi `clock_timestamp()` = waktu statement tulis, bukan waktu commit
(dan bukan awal transaksi, yang bisa berumur menit di pipeline enrich). Selisih tulis -> commit
bisa membuat baris muncul terlambat di bawah kursor klien, jadi baris yang lebih baru dari
`FEED_SETTLE_SECONDS` tidak dikembalikan. Persist adalah langkah terakhir sebelum commit, jadi 60 s
cukup; jika kelak ada penulis indikator yang menunda commit lebih lama, naikkan konstanta ini.
Lookup per id (`stix_ids`) tidak dikenai settle lag.

P7c (Task 15): pola yang sama digeneralisasi ke `entities`, `relationships` (REST
`/api/v2/entities|relationships`) dan ke feed gabungan koleksi TAXII `intel` (`intel_feed_page`).
Settle lag berlaku untuk semua jenis."""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cti_core.db.models.article import Article
from cti_core.db.models.entity import Entity, EntityMention, Relationship
from cti_core.db.models.indicator import Indicator, IndicatorSource
from cti_core.db.models.story import Story
from cti_core.entity import ENTITY_TYPES
from cti_core.indicator.marking import tlp_allowed
from cti_core.indicator.stix_id import indicator_uuid
from sqlalchemy import ColumnElement, Select, and_, func, literal, not_, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, noload, selectinload

from cti_api.services.stix import (
    STIX_INDICATOR_TYPES,
    entity_to_stix,
    indicator_to_stix,
    relationship_to_stix,
    report_stix_id,
    story_to_report,
)

FEED_SETTLE_SECONDS = 60


def encode_cursor(changed_at: datetime, indicator_id: int) -> str:
    raw = f"{changed_at.astimezone(UTC).isoformat()}|{indicator_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    """`ValueError` untuk apa pun yang cacat, termasuk cap waktu tanpa zona."""
    try:
        ts_raw, id_raw = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise ValueError("kursor tidak valid") from exc
    return _parse_ts_id(ts_raw, id_raw)


def _parse_ts_id(ts_raw: str, id_raw: str) -> tuple[datetime, int]:
    try:
        changed_at = datetime.fromisoformat(ts_raw)
        indicator_id = int(id_raw)
    except ValueError as exc:
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
            noload(Indicator.mentions),
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
        stmt = stmt.where(_settled(Indicator.feed_changed_at))

    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    items = rows[:limit]
    cursor = encode_cursor(items[-1].feed_changed_at, items[-1].id) if has_more else None
    return FeedPage(items=items, next_cursor=cursor)


# ── Generalisasi P7c: entities, relationships, feed gabungan `intel` ─────────


def _settled(col: Any) -> ColumnElement[bool]:
    """Baris lebih baru dari `FEED_SETTLE_SECONDS` belum diterbitkan (lihat docstring modul).
    Konstanta dibaca saat dipanggil supaya test bisa menggantinya."""
    return col <= func.now() - func.make_interval(0, 0, 0, 0, 0, 0, FEED_SETTLE_SECONDS)


def _entity_visible(e: Any, allowed: tuple[str, ...], *, stix: bool) -> ColumnElement[bool]:
    """TLP entitas diizinkan token. `stix=True`: juga bukan lokasi tanpa `external_id`, satu-
    satunya kasus `entity_to_stix` -> None, supaya ref ke entitas di koleksi `intel` selalu
    terselesaikan."""
    cond = e.tlp.in_(allowed)
    if stix:
        cond = and_(cond, not_(and_(e.type == "location", e.external_id.is_(None))))
    return cond


def _indicator_visible(i: Any, allowed: tuple[str, ...], *, stix: bool) -> ColumnElement[bool]:
    cond = i.tlp.in_(allowed)
    if stix:  # tipe tanpa pola STIX tidak pernah terbit (indicator_to_stix -> None)
        cond = and_(cond, i.type.in_(STIX_INDICATOR_TYPES))
    return cond


def _relationship_visible(allowed: tuple[str, ...], *, stix: bool) -> ColumnElement[bool]:
    """Relasi terlihat bila TLP-nya diizinkan DAN kedua ujungnya terlihat (spec 5.3): relasi ke
    entitas di atas TLP token tidak diterbitkan. Ujung tombstone/suppressed tetap terlihat (terbit
    sebagai objek revoked), jadi ref-nya terselesaikan."""
    src, dst = aliased(Entity), aliased(Entity)
    ind = aliased(Indicator)
    dst_ok = (
        select(1)
        .where(dst.id == Relationship.target_entity_id, _entity_visible(dst, allowed, stix=stix))
        .exists()
    )
    src_ok = or_(
        select(1)
        .where(src.id == Relationship.source_entity_id, _entity_visible(src, allowed, stix=stix))
        .exists(),
        select(1)
        .where(
            ind.id == Relationship.source_indicator_id,
            _indicator_visible(ind, allowed, stix=stix),
        )
        .exists(),
    )
    return and_(Relationship.tlp.in_(allowed), dst_ok, src_ok)


def _live_visible_entity(allowed: tuple[str, ...]) -> ColumnElement[bool]:
    """Entitas yang boleh masuk `object_refs` report: hidup (bukan tombstone/suppressed) dan
    terlihat."""
    return and_(
        Entity.suppressed.is_(False),
        Entity.merged_into_id.is_(None),
        _entity_visible(Entity, allowed, stix=True),
    )


def _story_has_refs(allowed: tuple[str, ...]) -> ColumnElement[bool]:
    """Story punya minimal satu ref terlihat; story tanpa ref tidak terbit (STIX mewajibkan
    `object_refs` tidak kosong). Harus sama dengan `_report_refs`."""
    ent = (
        select(1)
        .select_from(Article)
        .join(EntityMention, EntityMention.article_id == Article.id)
        .join(Entity, Entity.id == EntityMention.entity_id)
        .where(Article.story_id == Story.id, _live_visible_entity(allowed))
        .exists()
    )
    ind = (
        select(1)
        .select_from(Article)
        .join(IndicatorSource, IndicatorSource.article_id == Article.id)
        .join(Indicator, Indicator.id == IndicatorSource.indicator_id)
        .where(Article.story_id == Story.id, _indicator_visible(Indicator, allowed, stix=True))
        .exists()
    )
    return or_(ent, ind)


def _indicator_ref(stix_id: uuid.UUID | None, type_: str, value: str) -> str:
    return f"indicator--{stix_id or indicator_uuid(type_, value)}"


def _keyset(
    stmt: Select[Any],
    changed: Any,
    id_col: Any,
    *,
    limit: int,
    changed_after: datetime | None,
    after: ColumnElement[bool] | None,
    by_id: bool,
) -> Select[Any]:
    """Urut `(feed_changed_at, id)`, `limit + 1` baris, filter waktu, settle lag kecuali per id."""
    stmt = stmt.order_by(changed, id_col).limit(limit + 1)
    if changed_after is not None:
        stmt = stmt.where(changed > literal(changed_after))
    if after is not None:
        stmt = stmt.where(after)
    if not by_id:
        stmt = stmt.where(_settled(changed))
    return stmt


def _after_pair(changed: Any, id_col: Any, after: tuple[datetime, int] | None) -> Any:
    if after is None:
        return None
    return tuple_(changed, id_col) > tuple_(literal(after[0]), literal(after[1]))


@dataclass
class RowPage:
    """Satu halaman REST v2 non-indikator; `items` berisi baris siap diserialisasi router."""

    items: list[Any]
    next_cursor: str | None


@dataclass
class EntityRow:
    entity: Entity
    merged_into_stix_id: str | None


@dataclass
class RelationshipRow:
    relationship: Relationship
    source_ref: str
    target_ref: str


def _row_page(rows: list[Any], limit: int, key: Any) -> tuple[list[Any], str | None]:
    has_more = len(rows) > limit
    items = rows[:limit]
    cursor = encode_cursor(*key(items[-1])) if has_more else None
    return items, cursor


async def entity_feed_page(
    session: AsyncSession,
    *,
    max_tlp: str,
    limit: int,
    types: Collection[str] | None = None,
    changed_after: datetime | None = None,
    after: tuple[datetime, int] | None = None,
) -> RowPage:
    """Feed REST `/api/v2/entities`: semua entitas ber-TLP diizinkan, termasuk tombstone dan
    suppressed (konsumen perlu tahu pencabutannya). Kursor sama dengan feed indikator."""
    target = aliased(Entity)
    stmt = (
        select(Entity, target.stix_id)
        .outerjoin(target, target.id == Entity.merged_into_id)
        .where(_entity_visible(Entity, tlp_allowed(max_tlp), stix=False))
    )
    if types is not None:
        stmt = stmt.where(Entity.type.in_(list(types)))
    stmt = _keyset(
        stmt,
        Entity.feed_changed_at,
        Entity.id,
        limit=limit,
        changed_after=changed_after,
        after=_after_pair(Entity.feed_changed_at, Entity.id, after),
        by_id=False,
    )
    rows = [EntityRow(e, m) for e, m in (await session.execute(stmt)).tuples()]
    items, cursor = _row_page(rows, limit, lambda r: (r.entity.feed_changed_at, r.entity.id))
    return RowPage(items=items, next_cursor=cursor)


async def _relationship_ends(
    session: AsyncSession, rels: list[Relationship]
) -> dict[int, tuple[str, str]]:
    """Id STIX kedua ujung per relasi. Sumber indikator memakai id STIX indikator itu sendiri
    (sama dengan koleksi `indicators`)."""
    ent_ids = {r.target_entity_id for r in rels} | {
        r.source_entity_id for r in rels if r.source_entity_id is not None
    }
    ind_ids = {r.source_indicator_id for r in rels if r.source_indicator_id is not None}
    ents: dict[int, str] = {}
    if ent_ids:
        ents = dict(
            (await session.execute(select(Entity.id, Entity.stix_id).where(Entity.id.in_(ent_ids))))
            .tuples()
            .all()
        )
    inds: dict[int, str] = {}
    if ind_ids:
        rows = await session.execute(
            select(Indicator.id, Indicator.stix_id, Indicator.type, Indicator.value).where(
                Indicator.id.in_(ind_ids)
            )
        )
        inds = {i: _indicator_ref(sid, t, v) for i, sid, t, v in rows.tuples()}
    out: dict[int, tuple[str, str]] = {}
    for r in rels:
        src = ents[r.source_entity_id] if r.source_entity_id is not None else None
        if src is None and r.source_indicator_id is not None:
            src = inds[r.source_indicator_id]
        assert src is not None
        out[r.id] = (src, ents[r.target_entity_id])
    return out


async def relationship_feed_page(
    session: AsyncSession,
    *,
    max_tlp: str,
    limit: int,
    types: Collection[str] | None = None,
    changed_after: datetime | None = None,
    after: tuple[datetime, int] | None = None,
) -> RowPage:
    """Feed REST `/api/v2/relationships`: TLP relasi DAN kedua ujung diizinkan (spec 5.3)."""
    stmt = select(Relationship).where(_relationship_visible(tlp_allowed(max_tlp), stix=False))
    if types is not None:
        stmt = stmt.where(Relationship.relationship_type.in_(list(types)))
    stmt = _keyset(
        stmt,
        Relationship.feed_changed_at,
        Relationship.id,
        limit=limit,
        changed_after=changed_after,
        after=_after_pair(Relationship.feed_changed_at, Relationship.id, after),
        by_id=False,
    )
    rels = list((await session.execute(stmt)).scalars().all())
    rels, cursor = _row_page(rels, limit, lambda r: (r.feed_changed_at, r.id))
    ends = await _relationship_ends(session, rels)
    items = [RelationshipRow(r, *ends[r.id]) for r in rels]
    return RowPage(items=items, next_cursor=cursor)


# ── Feed gabungan koleksi TAXII `intel` ─────────────────────────────────────

INTEL_KINDS: tuple[str, ...] = ("entity", "relationship", "indicator", "report")
"""Urutan jenis pada waktu yang sama: objek yang dirujuk lebih dulu dari perujuknya."""
_KIND_RANK = {k: n for n, k in enumerate(INTEL_KINDS)}
_ENTITY_STIX_TYPES = frozenset(ENTITY_TYPES)


def encode_intel_cursor(changed_at: datetime, kind: str, row_id: int) -> str:
    raw = f"{changed_at.astimezone(UTC).isoformat()}|{kind}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_intel_cursor(cursor: str) -> tuple[datetime, str, int]:
    """`ValueError` untuk apa pun yang cacat, termasuk kursor koleksi `indicators` (2 bagian)."""
    try:
        ts_raw, kind, id_raw = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise ValueError("kursor tidak valid") from exc
    if kind not in _KIND_RANK:
        raise ValueError("kursor tidak valid: jenis tidak dikenal")
    changed_at, row_id = _parse_ts_id(ts_raw, id_raw)
    return changed_at, kind, row_id


@dataclass
class IntelPage:
    objects: list[dict[str, Any]]
    next_cursor: str | None


def _after_intel(
    changed: Any, id_col: Any, kind: str, after: tuple[datetime, str, int] | None
) -> ColumnElement[bool] | None:
    """Keyset atas `(feed_changed_at, rank jenis, id)` untuk satu tabel ber-rank tetap."""
    if after is None:
        return None
    at, after_kind, after_id = after
    rank, after_rank = _KIND_RANK[kind], _KIND_RANK[after_kind]
    if rank > after_rank:
        return changed >= literal(at)
    if rank < after_rank:
        return changed > literal(at)
    return tuple_(changed, id_col) > tuple_(literal(at), literal(after_id))


async def _report_refs(
    session: AsyncSession, story_ids: list[int], allowed: tuple[str, ...]
) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    """`object_refs` (entitas hidup + indikator artikel anggota, terlihat token) dan URL artikel
    per story. Syaratnya sama dengan `_story_has_refs`."""
    refs: dict[int, list[str]] = {sid: [] for sid in story_ids}
    urls: dict[int, list[str]] = {sid: [] for sid in story_ids}
    ent_rows = await session.execute(
        select(Article.story_id, Entity.stix_id)
        .join(EntityMention, EntityMention.article_id == Article.id)
        .join(Entity, Entity.id == EntityMention.entity_id)
        .where(Article.story_id.in_(story_ids), _live_visible_entity(allowed))
    )
    for sid, ref in ent_rows.tuples():
        refs[sid].append(ref)
    ind_rows = await session.execute(
        select(Article.story_id, Indicator.stix_id, Indicator.type, Indicator.value)
        .join(IndicatorSource, IndicatorSource.article_id == Article.id)
        .join(Indicator, Indicator.id == IndicatorSource.indicator_id)
        .where(Article.story_id.in_(story_ids), _indicator_visible(Indicator, allowed, stix=True))
    )
    for sid, stix_id, type_, value in ind_rows.tuples():
        refs[sid].append(_indicator_ref(stix_id, type_, value))
    url_rows = await session.execute(
        select(Article.story_id, Article.url).where(Article.story_id.in_(story_ids))
    )
    for sid, url in url_rows.tuples():
        urls[sid].append(url)
    return refs, urls


async def _report_ids_to_story_ids(session: AsyncSession, report_ids: set[str]) -> list[int]:
    """Id report = uuid5(id story), tak bisa dibalik dan Postgres inti tidak punya uuid5
    (Ruling 5), jadi lookup per id menghitung ulang id semua story. Hanya dipakai `match[id]` dan
    objek per id."""
    all_ids = (await session.execute(select(Story.id))).scalars().all()
    return [sid for sid in all_ids if report_stix_id(sid) in report_ids]


async def intel_feed_page(
    session: AsyncSession,
    *,
    max_tlp: str,
    limit: int,
    types: Collection[str] | None,
    changed_after: datetime | None,
    after: tuple[datetime, str, int] | None,
    stix_ids: Collection[str] | None,
) -> IntelPage:
    """Satu halaman koleksi `intel` (P7c spec 5.3): entitas, relasi, indikator dan report digabung
    menurut `(feed_changed_at, jenis, id)` dengan urutan jenis `INTEL_KINDS`. Tiap jenis di-query
    `limit + 1` baris sesudah kursor, digabung di Python, diambil `limit` pertama; kursor = baris
    terakhir. Deterministik karena kunci gabungan unik.

    Visibilitas per token: entitas (termasuk tombstone/suppressed, terbit revoked) ber-TLP
    diizinkan; relasi ber-TLP diizinkan dengan kedua ujung terlihat; indikator ber-TLP diizinkan
    dan berpola STIX; report (TLP:CLEAR, Ruling 32) yang `object_refs` tersaringnya tidak kosong.
    Jadi tiap `*_ref` objek menunjuk objek lain di koleksi yang sama untuk token itu.

    `types` = tipe STIX (`intrusion-set`, `relationship`, `indicator`, `report`, ...). `stix_ids`
    = lookup per id (tanpa settle lag)."""
    allowed = tlp_allowed(max_tlp)
    by_id = stix_ids is not None
    want = set(types) if types is not None else None
    ids = set(stix_ids) if stix_ids is not None else set()

    def wanted(kind_types: set[str] | frozenset[str]) -> bool:
        return want is None or bool(want & kind_types)

    def page(stmt: Select[Any], model: Any, kind: str) -> Select[Any]:
        return _keyset(
            stmt,
            model.feed_changed_at,
            model.id,
            limit=limit,
            changed_after=changed_after,
            after=_after_intel(model.feed_changed_at, model.id, kind, after),
            by_id=by_id,
        )

    # (waktu, rank, id, objek ORM)
    rows: list[tuple[datetime, int, int, Any]] = []

    if wanted(_ENTITY_STIX_TYPES):
        stmt = select(Entity).where(_entity_visible(Entity, allowed, stix=True))
        if want is not None:
            stmt = stmt.where(Entity.type.in_(sorted(want & _ENTITY_STIX_TYPES)))
        if by_id:
            stmt = stmt.where(Entity.stix_id.in_(sorted(ids)))
        for e in (await session.execute(page(stmt, Entity, "entity"))).scalars():
            rows.append((e.feed_changed_at, _KIND_RANK["entity"], e.id, e))

    if wanted({"relationship"}):
        stmt = select(Relationship).where(_relationship_visible(allowed, stix=True))
        if by_id:
            stmt = stmt.where(Relationship.stix_id.in_(sorted(ids)))
        for r in (await session.execute(page(stmt, Relationship, "relationship"))).scalars():
            rows.append((r.feed_changed_at, _KIND_RANK["relationship"], r.id, r))

    if wanted({"indicator"}):
        stmt = (
            select(Indicator)
            .where(_indicator_visible(Indicator, allowed, stix=True))
            .options(
                selectinload(Indicator.tags),
                noload(Indicator.sources),
                noload(Indicator.mentions),
                noload(Indicator.feedback),
            )
        )
        if by_id:
            uuids = []
            for sid in ids:
                kind, _, rest = sid.partition("--")
                if kind == "indicator":
                    try:
                        uuids.append(uuid.UUID(rest))
                    except ValueError:
                        continue
            stmt = stmt.where(Indicator.stix_id.in_(uuids))
        for i in (await session.execute(page(stmt, Indicator, "indicator"))).scalars():
            rows.append((i.feed_changed_at, _KIND_RANK["indicator"], i.id, i))

    if wanted({"report"}):
        stmt = select(Story).where(_story_has_refs(allowed))
        if by_id:
            report_ids = {sid for sid in ids if sid.startswith("report--")}
            story_ids = await _report_ids_to_story_ids(session, report_ids) if report_ids else []
            stmt = stmt.where(Story.id.in_(story_ids))
        for st in (await session.execute(page(stmt, Story, "report"))).scalars():
            rows.append((st.feed_changed_at, _KIND_RANK["report"], st.id, st))

    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    has_more = len(rows) > limit
    rows = rows[:limit]
    cursor = (
        encode_intel_cursor(rows[-1][0], INTEL_KINDS[rows[-1][1]], rows[-1][2])
        if has_more
        else None
    )

    rels = [r[3] for r in rows if r[1] == _KIND_RANK["relationship"]]
    ends = await _relationship_ends(session, rels) if rels else {}
    story_ids = [r[2] for r in rows if r[1] == _KIND_RANK["report"]]
    refs, urls = await _report_refs(session, story_ids, allowed) if story_ids else ({}, {})

    objects: list[dict[str, Any]] = []
    for _, rank, row_id, row in rows:
        kind = INTEL_KINDS[rank]
        obj: dict[str, Any] | None
        if kind == "entity":
            obj = entity_to_stix(row)
        elif kind == "relationship":
            obj = relationship_to_stix(row, *ends[row_id])
        elif kind == "indicator":
            obj = indicator_to_stix(row)
        else:
            obj = story_to_report(row, refs[row_id], urls[row_id])
        if obj is not None:  # tak terjadi bila filter SQL dan builder sepakat
            objects.append(obj)
    return IntelPage(objects=objects, next_cursor=cursor)
