"""Logika API entitas P7c (spec 5.2): daftar/detail, relasi + co-mention, mention per subjek,
tab ATT&CK, dan penulisan analis (buat, ubah, alias, merge/split/suppress, relasi, watch, profil).

Merge/split/suppress memakai `cti_core.entity.merge` (menulis baris audit sendiri, actor =
username); penulisan lain menulis audit di sini lewat `AsyncAuditLogRepo.write`. Pemanggil
(router) yang commit. Kesalahan bisnis dilempar sebagai `EntityNotFound` (404) atau
`EntityConflict` (409, pesannya jadi `detail`).

Tanggal artikel = `posted_on`, jatuh ke `created_at` bila kosong (Ruling 11); hitungan mention
30/90 hari dan jendela co-mention 365 hari memakai tanggal itu. Co-mention menghitung STORY:
artikel tanpa story dihitung sebagai story-nya sendiri (kunci `-article_id`).
"""

from __future__ import annotations

import base64
import binascii
import datetime
import json
import uuid
from collections.abc import Sequence
from typing import Any

from cti_core.attack_ttp import clean_attack_text
from cti_core.config import platform_name
from cti_core.db.models.article import Article
from cti_core.db.models.attack import AttackMitigation, AttackRelationship, AttackTechnique
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.entity import (
    Entity,
    EntityAlias,
    EntityMention,
    EntityProfile,
    EntityWatch,
    Relationship,
)
from cti_core.db.models.indicator import Indicator
from cti_core.db.models.story import Story
from cti_core.db.repositories.attack import build_navigator_layer
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.entity import live_entity
from cti_core.entity import alias_norm, collapse_ws, entity_stix_id, relationship_stix_id
from cti_core.entity.merge import (
    EntityMergeError,
    MergeResult,
    merge_entities_async,
    merge_preview_async,
    set_suppressed_async,
    split_aliases_async,
)
from cti_core.entity.resolve import TECHNIQUE
from sqlalchemy import ColumnElement, Date, and_, cast, distinct, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.schemas.entities import (
    AliasOut,
    AttackMitigationOut,
    AttackTechniqueOut,
    CoMention,
    EntityAttackResponse,
    EntityCreate,
    EntityCveItem,
    EntityCvesResponse,
    EntityDetail,
    EntityIndicatorItem,
    EntityIndicatorsResponse,
    EntityListItem,
    EntityListResponse,
    EntityRef,
    EntityRelationshipsResponse,
    EntityStoriesResponse,
    EntityStoryItem,
    EntityTimelineResponse,
    EntityUpdate,
    RelationshipCreate,
    RelationshipOut,
    TimelineMonth,
)

ACTOR = "intrusion-set"
_UPPER_IDS = (TECHNIQUE, "vulnerability")
"""Tipe yang id eksternalnya kanonik huruf besar (id teknik ATT&CK, id CVE)."""
CO_MENTION_DAYS = 365
CO_MENTION_LIMIT = 50


class EntityNotFound(LookupError):
    """-> 404."""


class EntityConflict(ValueError):
    """-> 409 `{detail}`."""


# ---------- helper ----------


def _article_day() -> ColumnElement[datetime.date]:
    return func.coalesce(Article.posted_on, cast(Article.created_at, Date))


def _today() -> datetime.date:
    return datetime.datetime.now(datetime.UTC).date()


def _sort_key() -> ColumnElement[str]:
    # collation C: urutan dan perbandingan kursor byte-wise, sama di semua locale server
    return func.lower(Entity.name).collate("C")


def encode_cursor(sort_key: str, entity_id: int) -> str:
    """`sort_key` = nilai `_sort_key()` dari baris SQL itu sendiri (bukan dihitung ulang)."""
    return base64.urlsafe_b64encode(json.dumps([sort_key, entity_id]).encode()).decode()


def decode_cursor(cursor: str) -> tuple[str, int]:
    """`ValueError` untuk kursor cacat (router -> 422)."""
    try:
        name, entity_id = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, TypeError, binascii.Error, UnicodeError) as exc:
        raise ValueError("kursor tidak valid") from exc
    if not isinstance(name, str) or not isinstance(entity_id, int) or entity_id < 1:
        raise ValueError("kursor tidak valid")
    return name, entity_id


def _ref(e: Entity) -> EntityRef:
    return EntityRef(id=e.id, type=e.type, name=e.name, external_id=e.external_id)


def _own_norm(e: Entity) -> str:
    """Alias identitas: id teknik untuk attack-pattern (Ruling 7), selain itu nama."""
    return alias_norm(e.external_id if e.type == TECHNIQUE and e.external_id else e.name)


async def _get(session: AsyncSession, entity_id: int) -> Entity:
    ent = await session.get(Entity, entity_id)
    if ent is None:
        raise EntityNotFound(f"entity {entity_id} not found")
    return ent


async def _get_live(session: AsyncSession, entity_id: int) -> Entity:
    ent = await _get(session, entity_id)
    if ent.merged_into_id is not None:
        raise EntityConflict(f"entity {entity_id} is merged into {ent.merged_into_id}")
    return ent


async def _mention_counts(session: AsyncSession, ids: Sequence[int]) -> dict[int, tuple[int, int]]:
    """Satu query per halaman: artikel berbeda per entitas dalam 30 dan 90 hari."""
    if not ids:
        return {}
    today, day = _today(), _article_day()
    d30, d90 = today - datetime.timedelta(days=30), today - datetime.timedelta(days=90)
    rows = await session.execute(
        select(
            EntityMention.entity_id,
            func.count(distinct(Article.id)).filter(day >= d30),
            func.count(distinct(Article.id)),
        )
        .join(Article, Article.id == EntityMention.article_id)
        .where(EntityMention.entity_id.in_(ids), day >= d90)
        .group_by(EntityMention.entity_id)
    )
    return {eid: (n30, n90) for eid, n30, n90 in rows.tuples()}


async def _watched(session: AsyncSession, client_id: str, ids: Sequence[int]) -> set[int]:
    if not ids:
        return set()
    rows = await session.scalars(
        select(EntityWatch.entity_id).where(
            EntityWatch.client_id == client_id, EntityWatch.entity_id.in_(ids)
        )
    )
    return set(rows)


async def _audit(
    session: AsyncSession, actor: str, ip: str, action: str, target: int, detail: dict[str, Any]
) -> None:
    await AsyncAuditLogRepo(session).write(
        username=actor, action=action, target_id=str(target), detail=detail, ip_address=ip
    )


async def _alias_owner(session: AsyncSession, type_: str, norm: str) -> EntityAlias | None:
    return (
        await session.scalars(
            select(EntityAlias).where(
                EntityAlias.entity_type == type_, EntityAlias.alias_norm == norm
            )
        )
    ).one_or_none()


# ---------- baca ----------


async def list_entities(
    session: AsyncSession,
    *,
    client_id: str,
    type: str | None,
    q: str | None,
    watched: bool,
    include_suppressed: bool,
    cursor: str | None,
    limit: int,
    identity_class: str | None = None,
) -> EntityListResponse:
    sort_key = _sort_key()
    stmt = select(Entity, sort_key).where(Entity.merged_into_id.is_(None))
    if not include_suppressed:
        stmt = stmt.where(Entity.suppressed.is_(False))
    if type:
        # daftar dipisah koma ("malware,tool"); validasi tipe ada di router
        stmt = stmt.where(Entity.type.in_([x for x in type.split(",") if x]))
    if identity_class:
        # hanya mempersempit `identity`; tipe lain tidak punya kelas dan tetap lolos
        stmt = stmt.where(or_(Entity.type != "identity", Entity.identity_class == identity_class))
    if q and (norm := alias_norm(q)):
        pattern = "%" + norm.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(
            select(EntityAlias.id)
            .where(EntityAlias.entity_id == Entity.id, EntityAlias.alias_norm.like(pattern))
            .exists()
        )
    if watched:
        stmt = stmt.where(
            Entity.id.in_(select(EntityWatch.entity_id).where(EntityWatch.client_id == client_id))
        )
    if cursor:
        name, last_id = decode_cursor(cursor)
        stmt = stmt.where(tuple_(sort_key, Entity.id) > tuple_(name, last_id))
    rows = list(
        (
            await session.execute(
                stmt.order_by(sort_key, Entity.id)
                .limit(limit + 1)
                .execution_options(populate_existing=True)  # alias segar sesudah merge/split
            )
        ).tuples()
    )
    page, more = [e for e, _ in rows[:limit]], len(rows) > limit
    # kursor menyimpan kunci urut hasil SQL (lower() Postgres), bukan str.lower() Python:
    # keduanya bisa beda untuk huruf non-ASCII, dan kursor harus sama dengan ORDER BY
    last_key = rows[limit - 1][1] if more else None
    ids = [e.id for e in page]
    counts = await _mention_counts(session, ids)
    watched_ids = await _watched(session, client_id, ids)
    return EntityListResponse(
        items=[
            EntityListItem(
                id=e.id,
                type=e.type,
                name=e.name,
                aliases=[a.alias for a in sorted(e.aliases, key=lambda a: a.id)],
                external_id=e.external_id,
                source=e.source,
                suppressed=e.suppressed,
                mentions_30d=counts.get(e.id, (0, 0))[0],
                mentions_90d=counts.get(e.id, (0, 0))[1],
                last_seen=e.last_seen,
                watched=e.id in watched_ids,
            )
            for e in page
        ],
        next_cursor=encode_cursor(last_key, page[-1].id) if last_key is not None else None,
    )


async def resolve_entity(
    session: AsyncSession, types: Sequence[str], name: str
) -> EntityRef | None:
    """Nama teks -> entitas (untuk teks tanpa `entity_id` di baliknya, mis. aktor di recap LLM).

    Alias dulu (alias entitas ter-merge sudah pindah ke target) tanpa `live_entity()`, jadi tanpa
    saringan suppressed: halaman entitas menampilkan yang suppressed dengan badge. Lalu
    `external_id` (T1566, CVE-..., kode negara `ID`) case-insensitive; tombstone diikuti ke
    ujung hidupnya."""
    stmt = (
        select(Entity.id)
        .join(EntityAlias, EntityAlias.entity_id == Entity.id)
        .where(
            EntityAlias.entity_type.in_(list(types)),
            EntityAlias.alias_norm == alias_norm(name),
            Entity.merged_into_id.is_(None),
        )
    )
    ids = list((await session.scalars(stmt.order_by(Entity.id))).all())
    if not ids and name.strip():
        ids = list(
            (
                await session.scalars(
                    select(Entity.id)
                    .where(
                        Entity.type.in_(list(types)),
                        func.lower(Entity.external_id) == name.strip().lower(),
                    )
                    .order_by(Entity.merged_into_id.is_not(None), Entity.id)
                )
            ).all()
        )
    if not ids:
        return None
    ent = await session.get(Entity, ids[0])
    seen: set[int] = set()
    while ent is not None and ent.merged_into_id is not None and ent.id not in seen:
        seen.add(ent.id)
        ent = await session.get(Entity, ent.merged_into_id)
    return None if ent is None else _ref(ent)


async def entity_detail(session: AsyncSession, entity_id: int, client_id: str) -> EntityDetail:
    """Tombstone dikembalikan apa adanya dengan `merged_into_id` terisi (web mengalihkan)."""
    ent = await _get(session, entity_id)
    await session.refresh(ent, ["aliases"])
    n30, n90 = (await _mention_counts(session, [ent.id])).get(ent.id, (0, 0))
    profile = (
        await session.scalars(select(EntityProfile).where(EntityProfile.entity_id == ent.id))
    ).one_or_none()
    tombs = (
        await session.scalars(
            select(Entity)
            .where(Entity.merged_into_id == ent.id)
            .order_by(Entity.feed_changed_at.desc(), Entity.id.desc())  # jam bump saat di-merge
        )
    ).all()
    return EntityDetail(
        id=ent.id,
        type=ent.type,
        name=ent.name,
        external_id=ent.external_id,
        source=ent.source,
        suppressed=ent.suppressed,
        mentions_30d=n30,
        mentions_90d=n90,
        last_seen=ent.last_seen,
        watched=ent.id in await _watched(session, client_id, [ent.id]),
        stix_id=ent.stix_id,
        description=ent.description,
        identity_class=ent.identity_class,
        merged_into_id=ent.merged_into_id,
        first_seen=ent.first_seen,
        aliases=[
            AliasOut(id=a.id, alias=a.alias, source=a.source)
            for a in sorted(ent.aliases, key=lambda a: a.id)
        ],
        profile=None if profile is None else profile.profile,
        profile_generated_at=None if profile is None else profile.generated_at,
        merged_from=[_ref(x) for x in tombs],
    )


async def _relationship_out(session: AsyncSession, r: Relationship) -> RelationshipOut:
    src = None if r.source_entity_id is None else await session.get(Entity, r.source_entity_id)
    tgt = await _get(session, r.target_entity_id)
    return RelationshipOut(
        id=r.id,
        stix_id=r.stix_id,
        relationship_type=r.relationship_type,
        source=None if src is None else _ref(src),
        source_indicator_id=r.source_indicator_id,
        target=_ref(tgt),
        confidence=r.confidence,
        provenance=r.provenance,
        description=r.description,
        first_seen=r.first_seen,
        last_seen=r.last_seen,
        created_by=r.created_by,
        revoked_at=r.revoked_at,
        revoked_by=r.revoked_by,
    )


async def co_mentions(session: AsyncSession, entity_id: int) -> list[CoMention]:
    """Entitas hidup yang disebut di story yang sama dengan `entity_id` dalam 365 hari terakhir
    (spec 5.2), dihitung per story, tanpa pasangan yang sudah punya relasi hidup (arah mana pun).
    Dihitung saat dibaca; tidak disimpan dan tidak diterbitkan."""
    cutoff = _today() - datetime.timedelta(days=CO_MENTION_DAYS)
    win = (
        select(
            Article.id.label("article_id"),
            func.coalesce(Article.story_id, -Article.id).label("story_key"),
        )
        .where(_article_day() >= cutoff)
        .subquery()
    )
    own_stories = (
        select(win.c.story_key)
        .join(EntityMention, EntityMention.article_id == win.c.article_id)
        .where(EntityMention.entity_id == entity_id)
    )
    related = (
        select(Relationship.target_entity_id)
        .where(Relationship.source_entity_id == entity_id, Relationship.revoked_at.is_(None))
        .union(
            select(Relationship.source_entity_id).where(
                Relationship.target_entity_id == entity_id,
                Relationship.revoked_at.is_(None),
                Relationship.source_entity_id.is_not(None),
            )
        )
    )
    stories = func.count(distinct(win.c.story_key))
    rows = (
        await session.execute(
            select(Entity, stories)
            .join(EntityMention, EntityMention.entity_id == Entity.id)
            .join(win, win.c.article_id == EntityMention.article_id)
            .where(
                win.c.story_key.in_(own_stories),
                Entity.id != entity_id,
                live_entity(),
                Entity.id.not_in(related),
            )
            .group_by(Entity.id)
            .order_by(stories.desc(), func.lower(Entity.name), Entity.id)
            .limit(CO_MENTION_LIMIT)
        )
    ).tuples()
    return [CoMention(entity=_ref(e), stories=n) for e, n in rows]


async def entity_relationships(
    session: AsyncSession, entity_id: int
) -> EntityRelationshipsResponse:
    await _get(session, entity_id)
    rels = (
        await session.scalars(
            select(Relationship)
            .where(
                or_(
                    Relationship.source_entity_id == entity_id,
                    Relationship.target_entity_id == entity_id,
                ),
                Relationship.revoked_at.is_(None),
            )
            .order_by(Relationship.id)
        )
    ).all()
    return EntityRelationshipsResponse(
        relationships=[await _relationship_out(session, r) for r in rels],
        co_mentions=await co_mentions(session, entity_id),
    )


async def entity_stories(
    session: AsyncSession, entity_id: int, *, limit: int, offset: int
) -> EntityStoriesResponse:
    """Story lewat artikel anggotanya yang menyebut entitas (spec 5.2), terbaru dulu."""
    await _get(session, entity_id)
    member = (
        select(Article.story_id, func.count(distinct(Article.id)).label("n"))
        .join(EntityMention, EntityMention.article_id == Article.id)
        .where(EntityMention.entity_id == entity_id, Article.story_id.is_not(None))
        .group_by(Article.story_id)
        .subquery()
    )
    total = await session.scalar(select(func.count()).select_from(member)) or 0
    rows = (
        await session.execute(
            select(Story, member.c.n)
            .join(member, member.c.story_id == Story.id)
            .order_by(Story.last_seen_at.desc(), Story.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).tuples()
    return EntityStoriesResponse(
        items=[
            EntityStoryItem(
                id=st.id,
                title=st.title,
                lead_source=st.lead_source,
                article_count=st.article_count,
                source_count=st.source_count,
                first_seen_at=st.first_seen_at,
                last_seen_at=st.last_seen_at,
                mentioned_articles=n,
            )
            for st, n in rows
        ],
        total=total,
    )


async def entity_indicators(
    session: AsyncSession, entity_id: int, *, limit: int, offset: int
) -> EntityIndicatorsResponse:
    await _get(session, entity_id)
    where = Indicator.id.in_(
        select(EntityMention.indicator_id).where(EntityMention.entity_id == entity_id)
    )
    total = await session.scalar(select(func.count(Indicator.id)).where(where)) or 0
    cols = (
        Indicator.id,
        Indicator.type,
        Indicator.value,
        Indicator.confidence_score,
        Indicator.first_seen_at,
        Indicator.last_seen_at,
        Indicator.revoked_at,
    )
    rows = await session.execute(
        select(*cols)
        .where(where)
        .order_by(Indicator.last_seen_at.desc(), Indicator.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return EntityIndicatorsResponse(
        items=[EntityIndicatorItem(**r._mapping) for r in rows], total=total
    )


async def entity_cves(
    session: AsyncSession, entity_id: int, client_id: str, *, limit: int, offset: int
) -> EntityCvesResponse:
    """Baris `cve_tracker` klien aktif yang menyebut entitas; untuk entitas `vulnerability`
    juga baris dengan `cve_id` = id CVE entitas itu."""
    ent = await _get(session, entity_id)
    conds: list[ColumnElement[bool]] = [
        CveTracker.id.in_(
            select(EntityMention.cve_tracker_id).where(EntityMention.entity_id == entity_id)
        )
    ]
    if ent.type == "vulnerability" and ent.external_id:
        conds.append(func.upper(CveTracker.cve_id) == ent.external_id.upper())
    where = and_(CveTracker.client_id == client_id, or_(*conds))
    total = await session.scalar(select(func.count(CveTracker.id)).where(where)) or 0
    cols = (
        CveTracker.id,
        CveTracker.cve_id,
        CveTracker.tech,
        CveTracker.cve_score,
        CveTracker.cve_severity,
        CveTracker.cisa_kev,
        CveTracker.published,
        CveTracker.detected_on,
    )
    rows = await session.execute(
        select(*cols)
        .where(where)
        .order_by(CveTracker.detected_on.desc(), CveTracker.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return EntityCvesResponse(items=[EntityCveItem(**r._mapping) for r in rows], total=total)


def _month_list(months: int, today: datetime.date) -> list[str]:
    y, m = today.year, today.month
    out: list[str] = []
    for _ in range(months):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


async def entity_timeline(
    session: AsyncSession, entity_id: int, *, months: int
) -> EntityTimelineResponse:
    """Artikel berbeda yang menyebut entitas per bulan (tanggal artikel), bulan kosong = 0."""
    await _get(session, entity_id)
    labels = _month_list(months, _today())
    start = datetime.date.fromisoformat(f"{labels[0]}-01")
    month = func.to_char(_article_day(), "YYYY-MM")
    rows = await session.execute(
        select(month, func.count(distinct(Article.id)))
        .join(EntityMention, EntityMention.article_id == Article.id)
        .where(EntityMention.entity_id == entity_id, _article_day() >= start)
        .group_by(month)
    )
    counts = {label: n for label, n in rows.tuples()}
    return EntityTimelineResponse(
        months=[TimelineMonth(month=label, articles=counts.get(label, 0)) for label in labels]
    )


async def entity_attack(session: AsyncSession, entity_id: int) -> EntityAttackResponse:
    """Teknik (lewat relasi `uses` hidup ke attack-pattern; attack-pattern = dirinya sendiri),
    mitigasi dari tabel `attack_*` per id teknik, dan layer Navigator (spec 5.2)."""
    ent = await _get(session, entity_id)
    if ent.type == TECHNIQUE:
        techs: list[Entity] = [ent]
    else:
        techs = list(
            (
                await session.scalars(
                    select(Entity)
                    .join(Relationship, Relationship.target_entity_id == Entity.id)
                    .where(
                        Relationship.source_entity_id == entity_id,
                        Relationship.relationship_type == "uses",
                        Relationship.revoked_at.is_(None),
                        Entity.type == TECHNIQUE,
                        live_entity(),
                    )
                    .order_by(Entity.external_id, Entity.id)
                )
            ).all()
        )
    ids = [t.external_id for t in techs if t.external_id]
    tactics: dict[str, list[str]] = {}
    stix_to_id: dict[str, str] = {}
    for attack_id, stix_id, tac in (
        await session.execute(
            select(AttackTechnique.attack_id, AttackTechnique.stix_id, AttackTechnique.tactics)
            .where(AttackTechnique.attack_id.in_(ids))
            .order_by(AttackTechnique.id)
        )
    ).tuples():
        stix_to_id[stix_id] = attack_id
        merged = tactics.setdefault(attack_id, [])
        merged.extend(t for t in tac if t not in merged)
    mitigated: dict[str, set[str]] = {}
    for src, tgt in (
        await session.execute(
            select(AttackRelationship.source_ref, AttackRelationship.target_ref).where(
                AttackRelationship.relationship_type == "mitigates",
                AttackRelationship.target_ref.in_(list(stix_to_id)),
            )
        )
    ).tuples():
        mitigated.setdefault(src, set()).add(stix_to_id[tgt])
    mits = (
        await session.scalars(
            select(AttackMitigation)
            .where(AttackMitigation.stix_id.in_(list(mitigated)))
            .order_by(AttackMitigation.mitigation_id)
        )
    ).all()
    by_mid: dict[str, AttackMitigationOut] = {}
    for m in mits:  # satu mitigasi bisa punya objek per domain dengan id sama
        out = by_mid.setdefault(
            m.mitigation_id,
            AttackMitigationOut(
                mitigation_id=m.mitigation_id,
                name=m.name,
                description=clean_attack_text(m.description)[:300],
                techniques=[],
            ),
        )
        out.techniques = sorted(set(out.techniques) | mitigated[m.stix_id])
    return EntityAttackResponse(
        techniques=[
            AttackTechniqueOut(**_ref(t).model_dump(), tactics=tactics.get(t.external_id or "", []))
            for t in techs
        ],
        mitigations=list(by_mid.values()),
        layer=build_navigator_layer(
            ids,
            name=f"{platform_name()} — {ent.name}",
            domain="enterprise-attack",
            description=f"Techniques used by {ent.name}",
        ),
    )


# ---------- tulis ----------


async def _check_alias_free(
    session: AsyncSession, type_: str, alias: str, owner_id: int | None
) -> EntityAlias | None:
    """Alias milik entitas lain -> 409; milik `owner_id` -> baris itu; bebas -> None."""
    row = await _alias_owner(session, type_, alias_norm(alias))
    if row is not None and row.entity_id != owner_id:
        raise EntityConflict(f"alias {alias!r} already belongs to entity {row.entity_id}")
    return row


async def _check_name_free(
    session: AsyncSession, type_: str, name: str, external_id: str | None, self_id: int | None
) -> None:
    match = (
        Entity.external_id == external_id
        if type_ == TECHNIQUE
        else func.lower(Entity.name) == name.lower()
    )
    taken = await session.scalar(
        select(Entity.id).where(
            Entity.type == type_,
            Entity.merged_into_id.is_(None),
            Entity.id != (self_id or 0),
            match,
        )
    )
    if taken is not None:
        raise EntityConflict(f"name {name!r} is already used by entity {taken}")
    if external_id and type_ != TECHNIQUE:  # teknik sudah dicek lewat external_id di atas
        taken = await session.scalar(
            select(Entity.id).where(
                Entity.type == type_,
                Entity.merged_into_id.is_(None),
                Entity.id != (self_id or 0),
                Entity.external_id == external_id,
            )
        )
        if taken is not None:
            raise EntityConflict(f"external_id {external_id!r} is already used by entity {taken}")


async def create_entity(session: AsyncSession, body: EntityCreate, *, actor: str, ip: str) -> int:
    display = collapse_ws(body.name)
    technique = body.type == TECHNIQUE
    external_id = collapse_ws(body.external_id or "") or None
    if external_id and body.type in _UPPER_IDS:
        external_id = external_id.upper()  # T1566.001, CVE-2024-1234: selalu huruf besar
    key = external_id if technique and external_id else display
    texts = [key] if technique else [display, *(collapse_ws(a) for a in body.aliases)]
    aliases = list({alias_norm(t): t for t in texts if alias_norm(t)}.values())
    for a in aliases:
        await _check_alias_free(session, body.type, a, None)
    await _check_name_free(session, body.type, display, external_id, None)
    stix = entity_stix_id(body.type, key)
    if await session.scalar(select(Entity.id).where(Entity.stix_id == stix)) is not None:
        stix = f"{body.type}--{uuid.uuid4()}"  # nama itu pernah dipakai entitas lain (tombstone)
    ent = Entity(
        type=body.type,
        stix_id=stix,
        name=display,
        description=body.description,
        external_id=external_id,
        identity_class=body.identity_class,
        source="analyst",
    )
    session.add(ent)
    await session.flush()
    for a in aliases:
        session.add(
            EntityAlias(
                entity_id=ent.id,
                entity_type=ent.type,
                alias=a,
                alias_norm=alias_norm(a),
                source="analyst",
            )
        )
    await session.flush()
    await _audit(
        session,
        actor,
        ip,
        "entity_create",
        ent.id,
        {"type": ent.type, "name": ent.name, "aliases": aliases, "external_id": external_id},
    )
    return ent.id


async def update_entity(
    session: AsyncSession, entity_id: int, body: EntityUpdate, *, actor: str, ip: str
) -> None:
    ent = await _get_live(session, entity_id)
    changes: dict[str, Any] = {}
    if body.name is not None and collapse_ws(body.name) != ent.name:
        name = collapse_ws(body.name)
        await _check_name_free(session, ent.type, name, ent.external_id, ent.id)
        # nama baru wajib juga jadi alias (spec 3.1); teknik: aliasnya id teknik (Ruling 7)
        if (
            ent.type != TECHNIQUE
            and await _check_alias_free(session, ent.type, name, ent.id) is None
        ):
            session.add(
                EntityAlias(
                    entity_id=ent.id,
                    entity_type=ent.type,
                    alias=name,
                    alias_norm=alias_norm(name),
                    source="analyst",
                )
            )
        changes["name"] = {"old": ent.name, "new": name}
        ent.name = name
    if "description" in body.model_fields_set and body.description != ent.description:
        changes["description"] = {"old": ent.description, "new": body.description}
        ent.description = body.description
    await session.flush()
    if changes:
        await _audit(session, actor, ip, "entity_update", ent.id, changes)
    if body.suppressed is not None and body.suppressed != ent.suppressed:
        await set_suppressed_async(session, ent.id, body.suppressed, actor=actor)


async def add_alias(
    session: AsyncSession, entity_id: int, alias: str, *, actor: str, ip: str
) -> AliasOut:
    ent = await _get_live(session, entity_id)
    if ent.type == TECHNIQUE:
        raise EntityConflict("attack-pattern aliases are the technique id only")
    text = collapse_ws(alias)
    if not text:
        raise EntityConflict("alias is empty")
    row = await _check_alias_free(session, ent.type, text, ent.id)
    if row is None:
        row = EntityAlias(
            entity_id=ent.id,
            entity_type=ent.type,
            alias=text,
            alias_norm=alias_norm(text),
            source="analyst",
        )
        session.add(row)
        await session.flush()
        await _audit(
            session, actor, ip, "entity_alias_add", ent.id, {"alias_id": row.id, "alias": text}
        )
    return AliasOut(id=row.id, alias=row.alias, source=row.source)


async def remove_alias(
    session: AsyncSession, entity_id: int, alias_id: int, *, actor: str, ip: str
) -> None:
    ent = await _get_live(session, entity_id)
    row = await session.get(EntityAlias, alias_id)
    if row is None or row.entity_id != ent.id:
        raise EntityNotFound(f"alias {alias_id} not found on entity {entity_id}")
    if row.alias_norm == _own_norm(ent):
        raise EntityConflict("the entity's own name alias cannot be removed")
    await session.delete(row)
    await session.flush()
    await _audit(
        session,
        actor,
        ip,
        "entity_alias_remove",
        ent.id,
        {"alias_id": alias_id, "alias": row.alias, "source": row.source},
    )


async def merge(
    session: AsyncSession, entity_id: int, into_id: int, *, actor: str, preview: bool
) -> MergeResult:
    await _get(session, entity_id)
    await _get(session, into_id)
    try:
        if preview:
            return await merge_preview_async(session, entity_id, into_id)
        return await merge_entities_async(session, entity_id, into_id, actor=actor)
    except EntityMergeError as exc:
        raise EntityConflict(str(exc)) from exc


async def split(session: AsyncSession, entity_id: int, alias_ids: list[int], *, actor: str) -> int:
    await _get(session, entity_id)
    try:
        target = await split_aliases_async(session, entity_id, alias_ids, actor=actor)
    except EntityMergeError as exc:
        raise EntityConflict(str(exc)) from exc
    return target.id


async def create_relationship(
    session: AsyncSession, body: RelationshipCreate, *, actor: str, ip: str
) -> RelationshipOut:
    """Edge yang sama sudah hidup -> 409; yang sudah di-revoke dihidupkan lagi (stix_id lama)."""
    src = await _get(session, body.source_id)
    tgt = await _get(session, body.target_id)
    for e in (src, tgt):
        if e.merged_into_id is not None or e.suppressed:
            raise EntityConflict(f"entity {e.id} is not live (merged or suppressed)")
    existing = (
        await session.scalars(
            select(Relationship).where(
                Relationship.source_entity_id == src.id,
                Relationship.source_indicator_id.is_(None),
                Relationship.relationship_type == body.relationship_type,
                Relationship.target_entity_id == tgt.id,
            )
        )
    ).one_or_none()
    if existing is not None and existing.revoked_at is None:
        raise EntityConflict(f"relationship already exists (id {existing.id})")
    unrevoked = existing is not None
    if existing is not None:
        rel = existing
        rel.revoked_at = rel.revoked_by = None
        rel.confidence = body.confidence
        rel.description = body.description
    else:
        stix = relationship_stix_id(src.stix_id, body.relationship_type, tgt.stix_id)
        if await session.scalar(select(Relationship.id).where(Relationship.stix_id == stix)):
            stix = f"relationship--{uuid.uuid4()}"  # stix_id itu kini milik edge lain (merge)
        rel = Relationship(
            stix_id=stix,
            relationship_type=body.relationship_type,
            source_entity_id=src.id,
            target_entity_id=tgt.id,
            confidence=body.confidence,
            description=body.description,
            provenance="analyst",
            created_by=actor,
        )
        session.add(rel)
    await session.flush()
    await session.refresh(rel)
    await _audit(
        session,
        actor,
        ip,
        "relationship_create",
        rel.id,
        {
            "source_id": src.id,
            "relationship_type": rel.relationship_type,
            "target_id": tgt.id,
            "confidence": rel.confidence,
            "unrevoked": unrevoked,
        },
    )
    return await _relationship_out(session, rel)


async def revoke_relationship(
    session: AsyncSession, relationship_id: int, *, actor: str, ip: str
) -> RelationshipOut:
    """Idempoten: relasi yang sudah revoked dikembalikan tanpa audit baru."""
    rel = await session.get(Relationship, relationship_id)
    if rel is None:
        raise EntityNotFound(f"relationship {relationship_id} not found")
    if rel.revoked_at is None:
        rel.revoked_at, rel.revoked_by = datetime.datetime.now(datetime.UTC), actor
        await session.flush()
        await _audit(session, actor, ip, "relationship_revoke", rel.id, {"stix_id": rel.stix_id})
    return await _relationship_out(session, rel)


async def set_watch(
    session: AsyncSession, entity_id: int, client_id: str, watched: bool, *, actor: str, ip: str
) -> bool:
    """Per klien aktif, seperti watchlist lama; audit hanya bila status berubah."""
    ent = await _get_live(session, entity_id)
    if watched:
        changed = (
            await session.execute(
                insert(EntityWatch)
                .values(client_id=client_id, entity_id=ent.id)
                .on_conflict_do_nothing()
                .returning(EntityWatch.id)
            )
        ).first() is not None
    else:
        row = (
            await session.scalars(
                select(EntityWatch).where(
                    EntityWatch.client_id == client_id, EntityWatch.entity_id == ent.id
                )
            )
        ).one_or_none()
        changed = row is not None
        if row is not None:
            await session.delete(row)
            await session.flush()
    if changed:
        await _audit(
            session,
            actor,
            ip,
            "entity_watch" if watched else "entity_unwatch",
            ent.id,
            {"client_id": client_id},
        )
    return watched


async def generate_profile(
    session: AsyncSession, entity_id: int, *, actor: str, ip: str
) -> dict[str, Any]:
    """Profil LLM aktor lewat fungsi yang sama dengan TA Room (`ta_profile.generate_ta_profile`,
    prompt tidak diduplikasi); hasilnya tersimpan di `entity_profiles` entitas ini."""
    from cti_api.services.ta_profile import generate_ta_profile

    ent = await _get_live(session, entity_id)
    if ent.type != ACTOR:
        raise EntityConflict("profiles are generated for intrusion-set entities only")
    profile = await generate_ta_profile(session, ent.name)
    await _audit(session, actor, ip, "entity_profile_generate", ent.id, {"name": ent.name})
    return profile
