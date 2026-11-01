"""Merge, split dan suppress entitas P7c (spec 3.4): eksak dan bisa dibalik.

Merge `A ke B` (tipe sama): alias A pindah ke B; mention, relasi, watch dan profil (hanya kalau B
belum punya) di-repoint ke B; A jadi tombstone (`merged_into_id = B`, `stix_id` tetap). Satu
transaksi pemanggil, satu baris `audit_log`. Merge otomatis Galaxy (spec 4.2) memakai jalur yang
sama dengan actor `system:galaxy`, jadi Split membatalkannya persis seperti merge analis (risiko
R1). Karena itu baris audit merge mencatat semua yang tidak bisa diturunkan ulang dari data:
id alias yang pindah dan mention A yang dibuang karena B sudah punya mention yang sama (unique
key mention). Split membaca baris itu untuk menghidupkan tombstone dan mengembalikan mention tsb.

Dedup lain saat merge:
- relasi dengan kunci unik sama di B: kembarannya menyimpan confidence tertinggi dan rentang seen
  terlebar; relasi A tetap di tombstone sebagai revoked (stix_id-nya mungkin sudah terbit lewat
  TAXII, jadi tidak dihapus). Relasi yang jadi B->B (mis. `A related-to B`) di-revoke.
- watch klien yang sama di A dan B jadi satu, `created_at` tertua dipertahankan.

Inti sinkron (dipanggil worker/CLI); pembungkus async lewat `session.run_sync` untuk API.
"""

from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.entity import Entity, EntityAlias, Relationship
from cti_core.entity import alias_norm, entity_stix_id
from cti_core.entity.resolve import TECHNIQUE


class EntityMergeError(ValueError):
    """Merge/split/suppress ditolak (tipe beda, id sama, sudah di-merge, alias tidak valid)."""


@dataclass
class MergeResult:
    moved_aliases: int
    moved_mentions: int
    """Mention yang di-repoint; duplikat yang dibuang dicatat di audit (`dropped_mentions`)."""
    moved_relationships: int
    """Relasi yang menyentuh sumber: di-repoint atau dilebur ke kembarannya di target."""
    moved_watches: int
    moved_profile: bool


def _audit(session: Session, actor: str, action: str, target: int, detail: dict[str, Any]) -> None:
    """Kolom sama dengan `AsyncAuditLogRepo.write` (tak ada kembaran sync); ip kosong = None."""
    session.add(
        AuditLogEntry(
            username=actor, action=action, target_id=str(target), detail=detail, ip_address=None
        )
    )
    session.flush()


def _lock(session: Session, *ids: int) -> dict[int, Entity]:
    """Kunci entitas `FOR NO KEY UPDATE`, urut id (Ruling 36). Bukan `FOR UPDATE`: mode itu bentrok
    dengan KEY SHARE yang diambil cek FK insert mention, sehingga enrichment yang sudah memegang
    kunci story-nya akan menunggu entitas ini sementara merge/suppress (lewat
    `trg_entities_feed_propagate`) menunggu story itu = deadlock. Merge/split/suppress hanya
    mengubah kolom non-kunci (`merged_into_id`, `suppressed`, seen), jadi UPDATE-nya sendiri juga
    hanya mengambil NO KEY UPDATE. Urutan kunci: entitas lalu story (trigger), sama dengan
    `_TOUCH_SEEN` yang tidak pernah menunggu entitas (SKIP LOCKED)."""
    rows = session.scalars(
        select(Entity)
        .where(Entity.id.in_(ids))
        .order_by(Entity.id)  # urutan kunci tetap: dua merge berlawanan tidak deadlock
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ).all()
    found = {e.id: e for e in rows}
    if missing := sorted(set(ids) - found.keys()):
        raise EntityMergeError(f"entities not found: {missing}")
    return found


def _ids(session: Session, sql: str, params: dict[str, Any]) -> list[Any]:
    return list(session.execute(text(sql), params).scalars())


def _lo(a: datetime.datetime | None, b: datetime.datetime | None) -> datetime.datetime | None:
    return min(a, b) if a and b else a or b


def _hi(a: Any, b: Any) -> Any:
    return max(a, b) if a is not None and b is not None else (a if b is None else b)


def _iso(v: datetime.datetime | None) -> str | None:
    return None if v is None else v.isoformat()


def _merge_relationships(
    session: Session, src: int, dst: int, actor: str, detail: dict[str, Any]
) -> int:
    rels = session.scalars(
        select(Relationship)
        .where(or_(Relationship.source_entity_id == src, Relationship.target_entity_id == src))
        .order_by(Relationship.id)
    ).all()
    for r in rels:
        new_src = dst if r.source_entity_id == src else r.source_entity_id
        new_tgt = dst if r.target_entity_id == src else r.target_entity_id
        twin = session.scalars(
            select(Relationship).where(
                Relationship.source_entity_id.is_not_distinct_from(new_src),
                Relationship.source_indicator_id.is_not_distinct_from(r.source_indicator_id),
                Relationship.relationship_type == r.relationship_type,
                Relationship.target_entity_id == new_tgt,
                Relationship.id != r.id,
            )
        ).one_or_none()
        if twin is None:
            r.source_entity_id, r.target_entity_id = new_src, new_tgt
            detail["repointed_relationship_ids"].append(r.id)
            survivor = r
        else:
            detail["folded_twins"].append(
                {
                    "id": twin.id,
                    "folded_id": r.id,
                    "confidence": twin.confidence,
                    "first_seen": _iso(twin.first_seen),
                    "last_seen": _iso(twin.last_seen),
                    "revoked_at": _iso(twin.revoked_at),
                }
            )
            # relasi A yang sudah revoked tidak menyumbang apa pun; kembaran yang di-revoke
            # analis tetap revoked (keputusan analis menang atas klaim A)
            if r.revoked_at is None:
                if twin.revoked_at is None:
                    twin.confidence = _hi(twin.confidence, r.confidence)
                    twin.first_seen = _lo(twin.first_seen, r.first_seen)
                    twin.last_seen = _hi(twin.last_seen, r.last_seen)
                else:
                    detail["kept_revoked_twin_ids"].append(twin.id)
                r.revoked_at, r.revoked_by = func.now(), actor
            detail["folded_relationship_ids"].append(r.id)
            survivor = twin
        if survivor.source_entity_id == survivor.target_entity_id and survivor.revoked_at is None:
            survivor.revoked_at, survivor.revoked_by = func.now(), actor
            detail["revoked_self_relationship_ids"].append(survivor.id)
        session.flush()
    return len(rels)


def merge_entities(session: Session, source_id: int, into_id: int, *, actor: str) -> MergeResult:
    if source_id == into_id:
        raise EntityMergeError("an entity cannot be merged into itself")
    ents = _lock(session, source_id, into_id)
    src, dst = ents[source_id], ents[into_id]
    if src.type != dst.type:
        raise EntityMergeError(f"cannot merge different types: {src.type} vs {dst.type}")
    for e in (src, dst):
        if e.merged_into_id is not None:
            raise EntityMergeError(f"entity {e.id} is already merged into {e.merged_into_id}")
        # Ruling 30: merge ke target suppressed menyembunyikan mention sumber; dari sumber
        # suppressed menghidupkan kembali mention yang sengaja disembunyikan. Unsuppress dulu.
        if e.suppressed:
            raise EntityMergeError(f"entity {e.id} is suppressed; unsuppress it before merging")
    p = {"src": source_id, "dst": into_id}

    # (entity_type, alias_norm) unik per tipe dan tipe sama, jadi pemindahan tak bisa bentrok
    alias_ids = sorted(
        _ids(
            session,
            "UPDATE entity_aliases SET entity_id = :dst WHERE entity_id = :src RETURNING id",
            p,
        )
    )
    dropped = session.execute(
        text(
            "DELETE FROM entity_mentions m USING entity_mentions d"
            " WHERE m.entity_id = :src AND d.entity_id = :dst"
            " AND m.article_id IS NOT DISTINCT FROM d.article_id"
            " AND m.indicator_id IS NOT DISTINCT FROM d.indicator_id"
            " AND m.cve_tracker_id IS NOT DISTINCT FROM d.cve_tracker_id"
            " AND m.role IS NOT DISTINCT FROM d.role"
            " RETURNING m.article_id, m.indicator_id, m.cve_tracker_id, m.method,"
            " m.matched_alias, m.role, m.evidence, m.extracted, m.created_at"
        ),
        p,
    ).mappings()
    dropped_mentions = [{**m, "created_at": m["created_at"].isoformat()} for m in dropped]
    mentions = _ids(
        session,
        "UPDATE entity_mentions SET entity_id = :dst WHERE entity_id = :src RETURNING id",
        p,
    )
    session.execute(
        text(
            "UPDATE entity_watches d SET created_at = LEAST(d.created_at, s.created_at)"
            " FROM entity_watches s"
            " WHERE s.entity_id = :src AND d.entity_id = :dst AND s.client_id = d.client_id"
        ),
        p,
    )
    dropped_watches = _ids(
        session,
        "DELETE FROM entity_watches s USING entity_watches d"
        " WHERE s.entity_id = :src AND d.entity_id = :dst AND s.client_id = d.client_id"
        " RETURNING s.client_id",
        p,
    )
    watches = _ids(
        session, "UPDATE entity_watches SET entity_id = :dst WHERE entity_id = :src RETURNING id", p
    )
    moved_profile = bool(
        _ids(
            session,
            "UPDATE entity_profiles SET entity_id = :dst WHERE entity_id = :src"
            " AND NOT EXISTS (SELECT 1 FROM entity_profiles WHERE entity_id = :dst) RETURNING id",
            p,
        )
    )
    detail: dict[str, Any] = {
        "source_id": source_id,
        "into_id": into_id,
        "alias_ids": alias_ids,
        "dropped_mentions": dropped_mentions,
        "dropped_watch_clients": dropped_watches,
        "moved_mention_ids": sorted(mentions),
        "moved_watch_ids": sorted(watches),
        "repointed_relationship_ids": [],
        "folded_relationship_ids": [],
        "folded_twins": [],
        "kept_revoked_twin_ids": [],
        "revoked_self_relationship_ids": [],
    }
    n_rels = _merge_relationships(session, source_id, into_id, actor, detail)

    src.merged_into_id = into_id
    dst.first_seen = _lo(dst.first_seen, src.first_seen)
    dst.last_seen = _hi(dst.last_seen, src.last_seen)
    session.flush()
    result = MergeResult(
        moved_aliases=len(alias_ids),
        moved_mentions=len(mentions),
        moved_relationships=n_rels,
        moved_watches=len(watches),
        moved_profile=moved_profile,
    )
    _audit(session, actor, "entity_merge", into_id, {**detail, **asdict(result)})
    session.refresh(src)  # koleksi alias di identity map basi sesudah UPDATE massal
    session.refresh(dst)
    return result


def merge_preview(session: Session, source_id: int, into_id: int) -> MergeResult:
    """Hitungan merge tanpa menulis: merge sungguhan di dalam SAVEPOINT lalu di-rollback, jadi
    angkanya pasti sama dengan `merge_entities` (termasuk dedup)."""
    with session.begin_nested() as savepoint:
        result = merge_entities(session, source_id, into_id, actor="system:preview")
        savepoint.rollback()
    return result


def _restore_mention(session: Session, entity_id: int, m: dict[str, Any]) -> bool:
    """Mention yang dibuang saat merge; dilewati kalau subjeknya sudah terhapus atau sudah ada."""
    return (
        session.execute(
            text(
                "INSERT INTO entity_mentions (article_id, indicator_id, cve_tracker_id, entity_id,"
                " method, matched_alias, role, evidence, extracted, created_at)"
                " SELECT :article_id, :indicator_id, :cve_tracker_id, :entity_id, :method,"
                " :matched_alias, :role, :evidence, CAST(:extracted AS jsonb),"
                " CAST(:created_at AS timestamptz)"
                " WHERE EXISTS (SELECT 1 FROM articles WHERE id = :article_id)"
                " OR EXISTS (SELECT 1 FROM indicators WHERE id = :indicator_id)"
                " OR EXISTS (SELECT 1 FROM cve_tracker WHERE id = :cve_tracker_id)"
                " ON CONFLICT DO NOTHING RETURNING id"
            ),
            {
                **m,
                "entity_id": entity_id,
                "extracted": None if m["extracted"] is None else json.dumps(m["extracted"]),
            },
        ).first()
        is not None
    )


def _check_revive(session: Session, tomb: Entity, norms: set[str]) -> None:
    """Tolak revive yang melanggar invarian sebelum ada yang ditulis."""
    technique = tomb.type == TECHNIQUE and tomb.external_id
    if alias_norm(tomb.external_id if technique and tomb.external_id else tomb.name) not in norms:
        raise EntityMergeError(
            f"reviving entity {tomb.id} requires its own name alias in the split"
        )
    clash = (
        Entity.external_id == tomb.external_id
        if technique
        else func.lower(Entity.name) == tomb.name.lower()
    )
    taken = session.scalar(
        select(Entity.id).where(
            Entity.type == tomb.type, Entity.merged_into_id.is_(None), Entity.id != tomb.id, clash
        )
    )
    if taken is not None:
        raise EntityMergeError(
            f"the name of entity {tomb.id} is already used by live entity {taken}"
        )


def split_aliases(session: Session, entity_id: int, alias_ids: list[int], *, actor: str) -> Entity:
    """Keluarkan `alias_ids` dari entitas: kembalikan ke pemilik aslinya (sumber merge terakhir
    yang memindah semua alias itu) kalau ia masih tombstone entitas ini (dihidupkan; alias nama
    sendirinya wajib ikut) atau sudah hidup lagi lewat split sebelumnya, selain itu buat entitas
    baru. Baris audit selalu mencatat `merge_audit_id` yang cocok (Task 7 mengenali merge Galaxy
    yang dibatalkan). Rantai merge (A->B->C) dibongkar terbalik: merge terbaru (B->C) yang cocok,
    jadi B dulu. Mention yang `matched_alias`-nya ternormalisasi ke salah satu alias ikut pindah.
    Relasi tidak dipindah (spec 3.4: dialog menampilkannya ke analis)."""
    ids = sorted(set(alias_ids))
    if not ids:
        raise EntityMergeError("alias_ids is empty")
    ent = _lock(session, entity_id)[entity_id]
    if ent.merged_into_id is not None:
        raise EntityMergeError(f"entity {entity_id} is already merged into {ent.merged_into_id}")
    by_id = {a.id: a for a in session.scalars(select(EntityAlias).where(EntityAlias.id.in_(ids)))}
    if set(by_id) != set(ids) or any(a.entity_id != entity_id for a in by_id.values()):
        raise EntityMergeError(f"aliases {ids} do not belong to entity {entity_id}")
    own = alias_norm(ent.external_id if ent.type == TECHNIQUE and ent.external_id else ent.name)
    if any(a.alias_norm == own for a in by_id.values()):
        raise EntityMergeError("the entity's own name alias cannot be split off")
    norms = {a.alias_norm for a in by_id.values()}

    merge_row = session.scalars(
        select(AuditLogEntry)
        .where(
            AuditLogEntry.action == "entity_merge",
            AuditLogEntry.detail["alias_ids"].contains(ids),
            # merge yang sumbernya entitas ini sendiri (B->C saat membongkar dari B) bukan asal
            AuditLogEntry.detail["source_id"].as_integer() != entity_id,
        )
        .order_by(AuditLogEntry.id.desc())
        .limit(1)
    ).one_or_none()
    owner = None
    if merge_row is not None:
        owner = session.get(
            Entity,
            merge_row.detail["source_id"],
            with_for_update={"key_share": True},  # NO KEY UPDATE, lihat `_lock`
            populate_existing=True,
        )
        # pemilik asli: tombstone yang masih menunjuk entitas ini (dihidupkan), atau sudah hidup
        # lagi karena split sebelumnya (alias sisanya dikembalikan ke entitas yang sama)
        if owner is not None and (
            owner.type != ent.type or owner.merged_into_id not in (entity_id, None)
        ):
            owner = None
    revived = owner is not None and owner.merged_into_id == entity_id
    if owner is not None:
        if revived:
            _check_revive(session, owner, norms)
            owner.merged_into_id = None
        target = owner
    else:
        first = by_id[alias_ids[0]].alias  # urutan pemanggil: alias pertama jadi nama
        key = first.upper() if ent.type == TECHNIQUE else first
        stix = entity_stix_id(ent.type, key)
        if session.scalar(select(Entity.id).where(Entity.stix_id == stix)) is not None:
            stix = f"{ent.type}--{uuid.uuid4()}"  # nama itu pernah dipakai entitas lain
        target = Entity(
            type=ent.type,
            stix_id=stix,
            name=key,
            source="analyst",
            external_id=key if ent.type == TECHNIQUE else None,
            identity_class=ent.identity_class,
        )
        session.add(target)
    session.flush()

    session.execute(
        update(EntityAlias)
        .where(EntityAlias.id.in_(ids))
        .values(entity_id=target.id)
        .execution_options(synchronize_session=False)
    )
    moved = _ids(
        session,
        "UPDATE entity_mentions SET entity_id = :new WHERE entity_id = :old"
        " AND entity_alias_norm(matched_alias) = ANY(:norms) RETURNING id",
        {"new": target.id, "old": entity_id, "norms": sorted(norms)},
    )
    restored = 0
    if owner is not None and merge_row is not None:
        for m in merge_row.detail.get("dropped_mentions", []):
            if alias_norm(m["matched_alias"]) in norms:
                restored += _restore_mention(session, target.id, m)
    _audit(
        session,
        actor,
        "entity_split",
        entity_id,
        {
            "source_id": entity_id,
            "into_id": target.id,
            "alias_ids": ids,
            "revived": revived,
            "returned_to_owner": owner is not None and not revived,
            "merge_audit_id": None if merge_row is None else merge_row.id,
            "moved_mentions": len(moved),
            "restored_mentions": restored,
        },
    )
    session.refresh(ent)
    session.refresh(target)
    return target


def set_suppressed(session: Session, entity_id: int, suppressed: bool, *, actor: str) -> Entity:
    """Mention dan alias tidak disentuh, jadi unsuppress memulihkan semuanya (spec 3.4)."""
    ent = _lock(session, entity_id)[entity_id]
    if ent.merged_into_id is not None:
        raise EntityMergeError(f"entity {entity_id} is already merged into {ent.merged_into_id}")
    ent.suppressed = suppressed
    session.flush()
    _audit(
        session,
        actor,
        "entity_suppress",
        entity_id,
        {"entity_id": entity_id, "suppressed": suppressed},
    )
    session.refresh(ent)
    return ent


async def merge_entities_async(
    session: AsyncSession, source_id: int, into_id: int, *, actor: str
) -> MergeResult:
    return await session.run_sync(merge_entities, source_id, into_id, actor=actor)


async def merge_preview_async(session: AsyncSession, source_id: int, into_id: int) -> MergeResult:
    return await session.run_sync(merge_preview, source_id, into_id)


async def split_aliases_async(
    session: AsyncSession, entity_id: int, alias_ids: list[int], *, actor: str
) -> Entity:
    return await session.run_sync(split_aliases, entity_id, alias_ids, actor=actor)


async def set_suppressed_async(
    session: AsyncSession, entity_id: int, suppressed: bool, *, actor: str
) -> Entity:
    return await session.run_sync(set_suppressed, entity_id, suppressed, actor=actor)
