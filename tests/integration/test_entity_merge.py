"""Merge, split dan suppress entitas (spec 3.4) pada Postgres NYATA.

Yang dijaga: merge eksak (alias, mention, relasi, watch, profil pindah dengan dedup), dan Split
membalikkan merge yang salah persis seperti semula (risiko R1: tombstone hidup lagi dengan
`stix_id` yang sama, mention kembali lewat `matched_alias`, termasuk mention yang di-dedup)."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from cti_core.db.models.article import Article
from cti_core.db.models.auth import AuditLogEntry, Client
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
from cti_core.entity import alias_norm, entity_stix_id
from cti_core.entity.merge import (
    EntityMergeError,
    MergeResult,
    merge_entities,
    merge_entities_async,
    merge_preview,
    set_suppressed,
    split_aliases,
    split_aliases_async,
)
from cti_core.entity.resolve import resolve
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


def _dt(day: int, month: int = 1) -> datetime.datetime:
    return datetime.datetime(2024, month, day, tzinfo=datetime.UTC)


def _make(s: Session, type_: str, name: str, *aliases: str) -> Entity:
    e = Entity(type=type_, stix_id=f"{type_}--{name}", name=name, source="analyst")
    s.add(e)
    s.flush()
    for a in (name, *aliases):
        s.add(
            EntityAlias(
                entity_id=e.id,
                entity_type=type_,
                alias=a,
                alias_norm=alias_norm(a),
                source="galaxy",
            )
        )
    s.flush()
    return e


_n = 0


def _article(s: Session) -> int:
    global _n
    _n += 1
    a = Article(url=f"http://m/{_n}", url_hash=f"merge-{_n}", title="t", source="src")
    s.add(a)
    s.flush()
    return a.id


def _mention(s: Session, entity: Entity, article_id: int, matched: str) -> None:
    s.add(
        EntityMention(
            article_id=article_id, entity_id=entity.id, method="dictionary", matched_alias=matched
        )
    )
    s.flush()


def _rel(s: Session, src: Entity, tgt: Entity, type_: str = "uses", **kw: Any) -> Relationship:
    r = Relationship(
        stix_id=f"relationship--{src.name}-{type_}-{tgt.name}",
        relationship_type=type_,
        source_entity_id=src.id,
        target_entity_id=tgt.id,
        provenance="analyst",
        **kw,
    )
    s.add(r)
    s.flush()
    return r


def _client(s: Session, cid: str) -> str:
    s.merge(Client(client_id=cid, name=cid))
    s.flush()
    return cid


def _alias_ids(s: Session, e: Entity) -> set[int]:
    return set(s.scalars(select(EntityAlias.id).where(EntityAlias.entity_id == e.id)))


def _mentions(s: Session, e: Entity) -> set[tuple[Any, ...]]:
    rows = s.execute(
        select(EntityMention.article_id, EntityMention.method, EntityMention.matched_alias).where(
            EntityMention.entity_id == e.id
        )
    )
    return {tuple(r) for r in rows}


def test_merge_moves_everything(db_session: Session) -> None:
    s = db_session
    a = _make(s, "intrusion-set", "APT-Alpha", "Alpha Bear")
    b = _make(s, "intrusion-set", "APT-Beta")
    mal = _make(s, "malware", "AlphaRAT")
    _mention(s, a, _article(s), "Alpha Bear")
    _rel(s, a, mal, confidence=60)
    s.add(EntityWatch(client_id=_client(s, "mc1"), entity_id=a.id))
    s.add(EntityProfile(entity_id=a.id, profile={"summary": "alpha"}))
    s.flush()
    stix_before = a.stix_id

    preview = merge_preview(s, a.id, b.id)
    assert len(_alias_ids(s, a)) == 2  # preview tidak menulis
    assert s.get(Entity, a.id).merged_into_id is None  # type: ignore[union-attr]

    result = merge_entities(s, a.id, b.id, actor="alice")
    assert isinstance(result, MergeResult)
    assert result == preview
    assert result == MergeResult(
        moved_aliases=2,
        moved_mentions=1,
        moved_relationships=1,
        moved_watches=1,
        moved_profile=True,
    )
    s.refresh(a)
    assert a.merged_into_id == b.id
    assert a.stix_id == stix_before
    assert _alias_ids(s, a) == set()
    assert {x.alias for x in s.get(Entity, b.id).aliases} == {  # type: ignore[union-attr]
        "APT-Alpha",
        "Alpha Bear",
        "APT-Beta",
    }
    assert resolve(s, "intrusion-set", "alpha bear", source="legacy").id == b.id
    assert {m[2] for m in _mentions(s, b)} == {"Alpha Bear"}
    rel = s.scalars(select(Relationship).where(Relationship.target_entity_id == mal.id)).one()
    assert rel.source_entity_id == b.id
    assert s.scalars(select(EntityWatch.entity_id).where(EntityWatch.client_id == "mc1")).all() == [
        b.id
    ]
    assert s.scalars(select(EntityProfile.entity_id)).all().count(b.id) == 1


def test_merge_dedups_relationship(db_session: Session) -> None:
    s = db_session
    a = _make(s, "intrusion-set", "Dup-A")
    b = _make(s, "intrusion-set", "Dup-B")
    mal = _make(s, "malware", "DupRAT")
    ra = _rel(s, a, mal, confidence=50, first_seen=_dt(1), last_seen=_dt(1, 2))
    rb = _rel(s, b, mal, confidence=80, first_seen=_dt(1, 3), last_seen=None)
    loop = _rel(s, a, b, "related-to")

    merge_entities(s, a.id, b.id, actor="alice")

    live = s.scalars(
        select(Relationship).where(
            Relationship.target_entity_id == mal.id, Relationship.revoked_at.is_(None)
        )
    ).all()
    assert [r.id for r in live] == [rb.id]
    s.refresh(rb)
    assert rb.source_entity_id == b.id
    assert rb.confidence == 80
    assert rb.first_seen == _dt(1)
    assert rb.last_seen == _dt(1, 2)
    # duplikat tetap ada (stix_id-nya sudah terbit) sebagai relasi revoked di tombstone
    s.refresh(ra)
    assert ra.revoked_at is not None and ra.revoked_by == "alice"
    assert ra.source_entity_id == a.id
    # A related-to B jadi B related-to B: tak bermakna, di-revoke
    s.refresh(loop)
    assert (loop.source_entity_id, loop.target_entity_id) == (b.id, b.id)
    assert loop.revoked_at is not None


def test_merge_dedups_mentions_and_watches(db_session: Session) -> None:
    s = db_session
    a = _make(s, "intrusion-set", "Mw-A")
    b = _make(s, "intrusion-set", "Mw-B")
    shared, only_a = _article(s), _article(s)
    _mention(s, a, shared, "Mw-A")
    _mention(s, b, shared, "Mw-B")
    _mention(s, a, only_a, "Mw-A")
    c1, c2 = _client(s, "mw1"), _client(s, "mw2")
    old = _dt(5)
    s.add_all(
        [
            EntityWatch(client_id=c1, entity_id=a.id, created_at=old),
            EntityWatch(client_id=c1, entity_id=b.id, created_at=_dt(9)),
            EntityWatch(client_id=c2, entity_id=a.id),
        ]
    )
    s.flush()

    result = merge_entities(s, a.id, b.id, actor="alice")

    assert result.moved_mentions == 1
    assert sorted(m[0] for m in _mentions(s, b)) == sorted([shared, only_a])
    assert _mentions(s, a) == set()
    assert result.moved_watches == 1
    watches = s.execute(
        select(EntityWatch.client_id, EntityWatch.entity_id, EntityWatch.created_at).order_by(
            EntityWatch.client_id
        )
    ).all()
    assert [(w[0], w[1]) for w in watches if w[0] in (c1, c2)] == [(c1, b.id), (c2, b.id)]
    assert next(w[2] for w in watches if w[0] == c1) == old


def test_merge_profile_only_if_target_has_none(db_session: Session) -> None:
    s = db_session
    a = _make(s, "malware", "Prof-A")
    b = _make(s, "malware", "Prof-B")
    c = _make(s, "malware", "Prof-C")
    s.add_all(
        [
            EntityProfile(entity_id=a.id, profile={"p": "a"}),
            EntityProfile(entity_id=b.id, profile={"p": "b"}),
        ]
    )
    s.flush()

    assert merge_entities(s, a.id, b.id, actor="alice").moved_profile is False
    profiles = dict(s.execute(select(EntityProfile.entity_id, EntityProfile.profile)).all())
    assert profiles[b.id] == {"p": "b"}
    assert profiles[a.id] == {"p": "a"}  # tetap di tombstone, tidak dihapus

    assert merge_entities(s, b.id, c.id, actor="alice").moved_profile is True
    profiles = dict(s.execute(select(EntityProfile.entity_id, EntityProfile.profile)).all())
    assert profiles[c.id] == {"p": "b"}


def test_merge_rejects_cross_type(db_session: Session) -> None:
    s = db_session
    actor = _make(s, "intrusion-set", "Rej-A")
    other = _make(s, "intrusion-set", "Rej-B")
    third = _make(s, "intrusion-set", "Rej-C")
    mal = _make(s, "malware", "Rej-M")
    assert issubclass(EntityMergeError, ValueError)
    with pytest.raises(EntityMergeError):
        merge_entities(s, actor.id, mal.id, actor="alice")
    with pytest.raises(EntityMergeError):
        merge_preview(s, actor.id, mal.id)
    with pytest.raises(EntityMergeError):
        merge_entities(s, actor.id, actor.id, actor="alice")
    merge_entities(s, actor.id, other.id, actor="alice")
    with pytest.raises(EntityMergeError):  # sumber sudah tombstone
        merge_entities(s, actor.id, third.id, actor="alice")
    with pytest.raises(EntityMergeError):  # target sudah tombstone
        merge_entities(s, third.id, actor.id, actor="alice")


def test_merge_attack_patterns_by_technique_id(db_session: Session) -> None:
    s = db_session
    t1 = resolve(s, "attack-pattern", "Phishing", source="attack", external_id="T9001")
    t2 = resolve(s, "attack-pattern", "Phishing", source="attack", external_id="T9002")
    merge_entities(s, t1.id, t2.id, actor="alice")
    assert resolve(s, "attack-pattern", "x", source="attack", external_id="t9001").id == t2.id
    t9001 = s.scalars(select(EntityAlias.id).where(EntityAlias.alias == "T9001")).all()
    restored = split_aliases(s, t2.id, t9001, actor="alice")
    assert restored.id == t1.id and restored.external_id == "T9001"


def test_split_after_merge_restores_exactly(db_session: Session) -> None:
    s = db_session
    a = _make(s, "intrusion-set", "Sp-Alpha", "Sp Alpha Bear")
    b = _make(s, "intrusion-set", "Sp-Beta")
    shared, art_a, art_b = _article(s), _article(s), _article(s)
    _mention(s, a, shared, "SP ALPHA  BEAR")  # bentuk teks beda, normalisasi sama
    _mention(s, b, shared, "Sp-Beta")
    _mention(s, a, art_a, "Sp-Alpha")
    _mention(s, b, art_b, "Sp-Beta")
    before = {
        "a_aliases": _alias_ids(s, a),
        "b_aliases": _alias_ids(s, b),
        "a_mentions": _mentions(s, a),
        "b_mentions": _mentions(s, b),
        "a_stix": a.stix_id,
    }

    merge_entities(s, a.id, b.id, actor="system:galaxy")
    assert _mentions(s, a) == set()
    restored = split_aliases(s, b.id, sorted(before["a_aliases"]), actor="alice")

    assert restored.id == a.id
    assert restored.merged_into_id is None
    assert restored.stix_id == before["a_stix"]
    assert _alias_ids(s, a) == before["a_aliases"]
    assert _alias_ids(s, b) == before["b_aliases"]
    assert _mentions(s, a) == before["a_mentions"]
    assert _mentions(s, b) == before["b_mentions"]
    assert resolve(s, "intrusion-set", "sp alpha bear", source="legacy").id == a.id


def test_split_new_entity_when_no_tombstone(db_session: Session) -> None:
    s = db_session
    b = _make(s, "intrusion-set", "Ns-Beta", "Ns Beta X", "Ns Beta Y")
    art1, art2 = _article(s), _article(s)
    _mention(s, b, art1, "ns beta x")
    _mention(s, b, art2, "Ns-Beta")
    ids = {x.alias: x.id for x in b.aliases}
    other = _make(s, "intrusion-set", "Ns-Other")

    with pytest.raises(EntityMergeError):  # alias nama sendiri tidak boleh keluar
        split_aliases(s, b.id, [ids["Ns-Beta"]], actor="alice")
    with pytest.raises(EntityMergeError):  # alias milik entitas lain
        split_aliases(s, b.id, [other.aliases[0].id], actor="alice")
    n_audit = s.scalar(select(func.count()).select_from(AuditLogEntry))
    with pytest.raises(EntityMergeError):
        split_aliases(s, b.id, [], actor="alice")
    assert s.scalar(select(func.count()).select_from(AuditLogEntry)) == n_audit
    assert {x.alias for x in s.get(Entity, b.id).aliases} == set(ids)  # type: ignore[union-attr]

    new = split_aliases(s, b.id, [ids["Ns Beta X"], ids["Ns Beta Y"]], actor="alice")

    assert new.id not in (b.id, other.id)
    assert (new.type, new.name, new.merged_into_id) == ("intrusion-set", "Ns Beta X", None)
    assert new.stix_id == entity_stix_id("intrusion-set", "Ns Beta X")
    assert {x.alias for x in new.aliases} == {"Ns Beta X", "Ns Beta Y"}
    assert {m[0] for m in _mentions(s, new)} == {art1}
    assert {m[0] for m in _mentions(s, b)} == {art2}


def test_suppress_keeps_mentions(db_session: Session) -> None:
    s = db_session
    e = _make(s, "malware", "Sup-M", "Sup alias")
    _mention(s, e, _article(s), "Sup-M")
    before = (_alias_ids(s, e), _mentions(s, e))

    assert set_suppressed(s, e.id, True, actor="alice").suppressed is True
    assert (_alias_ids(s, e), _mentions(s, e)) == before
    assert set_suppressed(s, e.id, False, actor="alice").suppressed is False
    assert (_alias_ids(s, e), _mentions(s, e)) == before


def test_audit_rows_written(db_session: Session) -> None:
    s = db_session
    a = _make(s, "tool", "Au-A", "Au alias")
    b = _make(s, "tool", "Au-B")
    a_aliases = sorted(_alias_ids(s, a))
    start = s.scalar(select(AuditLogEntry.id).order_by(AuditLogEntry.id.desc()).limit(1)) or 0

    merge_preview(s, a.id, b.id)  # tanpa baris audit
    merge_entities(s, a.id, b.id, actor="alice")
    split_aliases(s, b.id, a_aliases, actor="bob")
    set_suppressed(s, b.id, True, actor="carol")

    rows = s.scalars(
        select(AuditLogEntry).where(AuditLogEntry.id > start).order_by(AuditLogEntry.id)
    ).all()
    assert [(r.action, r.username, r.ip_address) for r in rows] == [
        ("entity_merge", "alice", None),
        ("entity_split", "bob", None),
        ("entity_suppress", "carol", None),
    ]
    merge, split, sup = (r.detail for r in rows)
    assert (merge["source_id"], merge["into_id"], merge["alias_ids"]) == (a.id, b.id, a_aliases)
    assert rows[0].target_id == str(b.id)
    assert (split["source_id"], split["into_id"], split["alias_ids"]) == (b.id, a.id, a_aliases)
    assert split["revived"] is True
    assert (sup["entity_id"], sup["suppressed"]) == (b.id, True)


async def test_merge_async_wrapper(async_db_session: AsyncSession) -> None:
    s = async_db_session
    a = Entity(type="campaign", stix_id="campaign--as-a", name="As-A", source="analyst")
    b = Entity(type="campaign", stix_id="campaign--as-b", name="As-B", source="analyst")
    s.add_all([a, b])
    await s.flush()
    result = await merge_entities_async(s, a.id, b.id, actor="alice")
    assert result.moved_aliases == 0
    await s.refresh(a)
    assert a.merged_into_id == b.id


def _state(s: Session, *ents: Entity) -> list[Any]:
    return [(_alias_ids(s, e), _mentions(s, e)) for e in ents]


def test_two_step_split_restores_pre_merge(db_session: Session) -> None:
    """Split sebagian (tombstone hidup lagi), lalu sisanya: alias kembali ke A yang SAMA."""
    s = db_session
    a = _make(s, "intrusion-set", "Two-A", "Two a1", "Two a2")
    b = _make(s, "intrusion-set", "Two-B")
    shared, art1, art2 = _article(s), _article(s), _article(s)
    _mention(s, a, shared, "Two a2")  # dibuang saat merge (B juga di artikel ini)
    _mention(s, b, shared, "Two-B")
    _mention(s, a, art1, "Two a1")
    _mention(s, a, art2, "Two-A")
    ids = {x.alias: x.id for x in a.aliases}
    before = _state(s, a, b)

    merge_entities(s, a.id, b.id, actor="system:galaxy")
    first = split_aliases(s, b.id, [ids["Two-A"], ids["Two a1"]], actor="alice")
    second = split_aliases(s, b.id, [ids["Two a2"]], actor="alice")

    assert first.id == second.id == a.id
    assert _state(s, a, b) == before


def test_revive_requires_own_name_alias(db_session: Session) -> None:
    s = db_session
    a = _make(s, "malware", "Own-A", "Own x")
    b = _make(s, "malware", "Own-B")
    x_id = next(x.id for x in a.aliases if x.alias == "Own x")
    merge_entities(s, a.id, b.id, actor="alice")
    before = _state(s, a, b)
    with pytest.raises(EntityMergeError):
        split_aliases(s, b.id, [x_id], actor="alice")
    assert _state(s, a, b) == before
    s.refresh(a)
    assert a.merged_into_id == b.id


def test_revive_rejects_taken_name(db_session: Session) -> None:
    s = db_session
    a = _make(s, "malware", "Taken-A")
    b = _make(s, "malware", "Taken-B")
    a_ids = sorted(_alias_ids(s, a))
    merge_entities(s, a.id, b.id, actor="alice")
    # nama tombstone tak dijaga indeks unik, jadi entitas hidup baru boleh memakainya
    s.add(Entity(type="malware", stix_id="malware--taken-new", name="taken-a", source="analyst"))
    s.flush()
    with pytest.raises(EntityMergeError):
        split_aliases(s, b.id, a_ids, actor="alice")


def test_split_records_matched_merge_without_revive(db_session: Session) -> None:
    s = db_session
    a = _make(s, "tool", "Ch-A", "Ch a1")
    b = _make(s, "tool", "Ch-B")
    d = _make(s, "tool", "Ch-D")
    ids = {x.alias: x.id for x in a.aliases}
    merge_entities(s, a.id, b.id, actor="system:galaxy")
    merge_row = s.scalars(
        select(AuditLogEntry)
        .where(AuditLogEntry.action == "entity_merge")
        .order_by(AuditLogEntry.id.desc())
    ).first()
    assert merge_row is not None
    split_aliases(s, b.id, [ids["Ch-A"]], actor="alice")  # A hidup lagi tanpa "Ch a1"
    merge_entities(s, a.id, d.id, actor="alice")  # A pindah ke D
    new = split_aliases(s, b.id, [ids["Ch a1"]], actor="alice")  # pemilik A menunjuk D, bukan B
    assert new.id not in (a.id, b.id, d.id)
    split = s.scalars(
        select(AuditLogEntry)
        .where(AuditLogEntry.action == "entity_split")
        .order_by(AuditLogEntry.id.desc())
    ).first()
    assert split is not None
    assert split.detail["merge_audit_id"] == merge_row.id
    assert (split.detail["revived"], split.detail["returned_to_owner"]) == (False, False)


def test_chain_unwinds_in_reverse(db_session: Session) -> None:
    s = db_session
    a = _make(s, "tool", "Rc-A")
    b = _make(s, "tool", "Rc-B")
    c = _make(s, "tool", "Rc-C")
    a_ids, b_ids = sorted(_alias_ids(s, a)), sorted(_alias_ids(s, b))
    merge_entities(s, a.id, b.id, actor="alice")
    merge_entities(s, b.id, c.id, actor="alice")
    with pytest.raises(EntityMergeError):  # merge terbaru B->C: B harus kembali dulu
        split_aliases(s, c.id, a_ids, actor="alice")
    assert split_aliases(s, c.id, a_ids + b_ids, actor="alice").id == b.id
    assert split_aliases(s, b.id, a_ids, actor="alice").id == a.id


def test_merge_relationship_revocation_rules(db_session: Session) -> None:
    s = db_session
    a = _make(s, "intrusion-set", "Rv-A")
    b = _make(s, "intrusion-set", "Rv-B")
    m1, m2 = _make(s, "malware", "Rv-M1"), _make(s, "malware", "Rv-M2")
    # A revoked -> tidak menyumbang confidence/seen ke kembaran hidup
    dead_a = _rel(s, a, m1, confidence=99, first_seen=_dt(1), revoked_at=_dt(2))
    live_b = _rel(s, b, m1, confidence=40, first_seen=_dt(5))
    # A hidup, kembaran B di-revoke analis -> kembaran tetap revoked
    live_a = _rel(s, a, m2, confidence=70)
    dead_b = _rel(s, b, m2, confidence=30, revoked_at=_dt(3), revoked_by="analyst1")
    moved = _rel(s, a, _make(s, "tool", "Rv-T"))

    merge_entities(s, a.id, b.id, actor="alice")

    for r in (dead_a, live_b, live_a, dead_b, moved):
        s.refresh(r)
    assert (live_b.confidence, live_b.first_seen, live_b.revoked_at) == (40, _dt(5), None)
    assert dead_b.revoked_at == _dt(3) and dead_b.revoked_by == "analyst1"
    assert live_a.revoked_at is not None and live_a.source_entity_id == a.id
    detail = s.scalars(
        select(AuditLogEntry.detail)
        .where(AuditLogEntry.action == "entity_merge")
        .order_by(AuditLogEntry.id.desc())
    ).first()
    assert detail is not None
    assert detail["repointed_relationship_ids"] == [moved.id]
    assert detail["kept_revoked_twin_ids"] == [dead_b.id]
    twins = {t["id"]: t for t in detail["folded_twins"]}
    assert twins[dead_b.id]["confidence"] == 30
    assert twins[dead_b.id]["revoked_at"] == _dt(3).isoformat()
    assert twins[live_b.id]["folded_id"] == dead_a.id


def test_merge_audit_lists_repointed_rows(db_session: Session) -> None:
    s = db_session
    a = _make(s, "intrusion-set", "Ar-A")
    b = _make(s, "intrusion-set", "Ar-B")
    _mention(s, a, _article(s), "Ar-A")
    w = EntityWatch(client_id=_client(s, "ar1"), entity_id=a.id)
    s.add(w)
    s.flush()
    mention_ids = s.scalars(select(EntityMention.id).where(EntityMention.entity_id == a.id)).all()
    merge_entities(s, a.id, b.id, actor="alice")
    detail = s.scalars(
        select(AuditLogEntry.detail)
        .where(AuditLogEntry.action == "entity_merge")
        .order_by(AuditLogEntry.id.desc())
    ).first()
    assert detail is not None
    assert detail["moved_mention_ids"] == list(mention_ids)
    assert detail["moved_watch_ids"] == [w.id]


def test_merge_indicator_and_cve_mentions(db_session: Session) -> None:
    s = db_session
    _client(s, "icv")
    a = _make(s, "intrusion-set", "Ic-A", "Ic alias")
    b = _make(s, "intrusion-set", "Ic-B")
    ind = Indicator(type="ip", value="192.0.2.91")
    cve = CveTracker(cve_id="CVE-2026-9191", client_id="icv", tech="x")
    ind2 = Indicator(type="ip", value="192.0.2.92")
    s.add_all([ind, cve, ind2])
    s.flush()
    for kw in ({"indicator_id": ind.id}, {"cve_tracker_id": cve.id}, {"indicator_id": ind2.id}):
        s.add(EntityMention(entity_id=a.id, method="explicit", matched_alias="Ic alias", **kw))
    s.add(
        EntityMention(entity_id=b.id, method="explicit", matched_alias="Ic-B", indicator_id=ind2.id)
    )
    s.flush()
    rows = lambda e: set(  # noqa: E731
        s.execute(
            select(EntityMention.indicator_id, EntityMention.cve_tracker_id).where(
                EntityMention.entity_id == e.id
            )
        ).all()
    )
    before = (rows(a), rows(b))

    assert merge_entities(s, a.id, b.id, actor="alice").moved_mentions == 2
    assert rows(b) == {(ind.id, None), (None, cve.id), (ind2.id, None)}
    split_aliases(
        s,
        b.id,
        sorted(_alias_ids(s, b) - {x.id for x in b.aliases if x.alias == "Ic-B"}),
        actor="alice",
    )
    assert (rows(a), rows(b)) == before


async def test_split_async_wrapper(async_db_session: AsyncSession) -> None:
    s = async_db_session
    b = Entity(type="campaign", stix_id="campaign--as-split", name="As-S", source="analyst")
    s.add(b)
    await s.flush()
    s.add_all(
        [
            EntityAlias(
                entity_id=b.id,
                entity_type="campaign",
                alias=x,
                alias_norm=alias_norm(x),
                source="analyst",
            )
            for x in ("As-S", "As other")
        ]
    )
    await s.flush()
    other_id = (
        await s.scalars(select(EntityAlias.id).where(EntityAlias.alias == "As other"))
    ).one()
    new = await split_aliases_async(s, b.id, [other_id], actor="alice")
    assert new.name == "As other"
    assert [x.alias for x in new.aliases] == ["As other"]
