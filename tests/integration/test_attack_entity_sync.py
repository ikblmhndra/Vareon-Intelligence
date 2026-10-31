"""Integration test `upsert_attack_entities` (P7c Task 9): objek ATT&CK (grup, software, teknik,
campaign) + relasinya masuk ke `entities`/`entity_aliases`/`relationships` sesudah sync domain.
Hasilnya harus sama dengan backfill migrasi (stix_id ATT&CK, alias `attack`, confidence 85)."""

from __future__ import annotations

import copy
from typing import Any

import httpx
import pytest
from cti_core.db.models.article import Article
from cti_core.db.models.entity import Entity, EntityAlias, EntityMention, Relationship
from cti_core.db.repositories import attack as attack_mod
from cti_core.db.repositories.attack import AsyncAttackSyncRepo, upsert_attack_entities
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

GROUP = "intrusion-set--11111111-1111-4111-8111-111111111111"
MALWARE = "malware--22222222-2222-4222-8222-222222222222"
TECH = "attack-pattern--33333333-3333-4333-8333-333333333333"
CAMPAIGN = "campaign--44444444-4444-4444-8444-444444444444"
REVOKED_GROUP = "intrusion-set--55555555-5555-4555-8555-555555555555"


def _ext(ext_id: str) -> list[dict[str, str]]:
    return [{"source_name": "mitre-attack", "external_id": ext_id, "url": f"https://x/{ext_id}"}]


def _rel(n: int, rtype: str, src: str, dst: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": "relationship",
        "id": f"relationship--0000000{n}-0000-4000-8000-000000000000",
        "relationship_type": rtype,
        "source_ref": src,
        "target_ref": dst,
        "description": f"rel {n}",
        **extra,
    }


def _bundle() -> list[dict[str, Any]]:
    return [
        {
            "type": "intrusion-set",
            "id": GROUP,
            "name": "Test Group",
            "aliases": ["Test Group", "Group Alias"],
            "description": "grup uji",
            "external_references": _ext("G9001"),
        },
        {
            "type": "malware",
            "id": MALWARE,
            "name": "TestMal",
            "x-mitre-aliases": ["TestMal", "Mal Alias"],
            "description": "malware uji",
            "external_references": _ext("S9001"),
        },
        {
            "type": "attack-pattern",
            "id": TECH,
            "name": "Spearphishing Attachment",
            "description": "teknik uji",
            "external_references": _ext("T9001.001"),
        },
        {
            "type": "campaign",
            "id": CAMPAIGN,
            "name": "Operation Test",
            "aliases": ["Op Test"],
            "description": "campaign uji",
            "external_references": _ext("C9001"),
        },
        {
            "type": "intrusion-set",
            "id": REVOKED_GROUP,
            "name": "Revoked Group",
            "revoked": True,
            "external_references": _ext("G9002"),
        },
        _rel(1, "uses", GROUP, MALWARE),
        _rel(2, "uses", CAMPAIGN, TECH),
        _rel(3, "attributed-to", CAMPAIGN, GROUP),
        _rel(4, "revoked-by", REVOKED_GROUP, GROUP),  # tipe di luar CHECK -> dilewati
        _rel(5, "mitigates", GROUP, MALWARE),  # tipe di luar CHECK -> dilewati
        _rel(6, "uses", GROUP, REVOKED_GROUP),  # ujung tidak jadi entitas -> dilewati
        _rel(7, "uses", MALWARE, TECH, revoked=True),  # relasi revoked -> dilewati
    ]


async def _entity(session: AsyncSession, stix_id: str) -> Entity | None:
    return (
        await session.execute(select(Entity).where(Entity.stix_id == stix_id))
    ).scalar_one_or_none()


async def test_sync_creates_campaign_entity(async_db_session: AsyncSession) -> None:
    counts = await upsert_attack_entities(async_db_session, _bundle())

    camp = await _entity(async_db_session, CAMPAIGN)
    assert camp is not None
    assert (camp.type, camp.external_id, camp.source, camp.name) == (
        "campaign",
        "C9001",
        "attack",
        "Operation Test",
    )
    group = await _entity(async_db_session, GROUP)
    malware = await _entity(async_db_session, MALWARE)
    tech = await _entity(async_db_session, TECH)
    assert group and malware and tech
    assert (group.type, group.external_id) == ("intrusion-set", "G9001")
    assert (malware.type, malware.external_id) == ("malware", "S9001")
    assert (tech.type, tech.external_id, tech.name) == (
        "attack-pattern",
        "T9001.001",
        "Spearphishing Attachment",
    )
    assert await _entity(async_db_session, REVOKED_GROUP) is None

    aliases = (
        await async_db_session.execute(
            select(EntityAlias.entity_id, EntityAlias.alias_norm, EntityAlias.source).where(
                EntityAlias.entity_id.in_([group.id, malware.id, tech.id, camp.id])
            )
        )
    ).all()
    by_entity: dict[int, set[str]] = {}
    for eid, norm, src in aliases:
        assert src == "attack"
        by_entity.setdefault(eid, set()).add(norm)
    assert by_entity[group.id] == {"test group", "group alias"}
    assert by_entity[malware.id] == {"testmal", "mal alias"}
    assert by_entity[tech.id] == {"t9001.001"}  # Ruling 7: hanya id teknik
    assert by_entity[camp.id] == {"operation test", "op test"}

    rels = (await async_db_session.execute(select(Relationship))).scalars().all()
    got = {(r.relationship_type, r.source_entity_id, r.target_entity_id) for r in rels}
    assert got == {
        ("uses", group.id, malware.id),
        ("uses", camp.id, tech.id),
        ("attributed-to", camp.id, group.id),
    }
    assert all(r.provenance == "attack" and r.confidence == 85 for r in rels)
    assert {r.stix_id for r in rels} == {_rel(n, "", "", "")["id"] for n in (1, 2, 3)}
    assert counts == {
        "intrusion-set": 1,
        "malware": 1,
        "tool": 0,
        "attack-pattern": 1,
        "campaign": 1,
        "relationship": 3,
    }


async def test_sync_is_idempotent(async_db_session: AsyncSession) -> None:
    first = await upsert_attack_entities(async_db_session, _bundle())
    n_ent = len((await async_db_session.execute(select(Entity.id))).all())
    n_alias = len((await async_db_session.execute(select(EntityAlias.id))).all())
    n_rel = len((await async_db_session.execute(select(Relationship.id))).all())

    second = await upsert_attack_entities(async_db_session, _bundle())

    assert second == first
    assert len((await async_db_session.execute(select(Entity.id))).all()) == n_ent
    assert len((await async_db_session.execute(select(EntityAlias.id))).all()) == n_alias
    assert len((await async_db_session.execute(select(Relationship.id))).all()) == n_rel


async def test_sync_keeps_analyst_aliases(async_db_session: AsyncSession) -> None:
    await upsert_attack_entities(async_db_session, _bundle())
    group = await _entity(async_db_session, GROUP)
    assert group
    async_db_session.add(
        EntityAlias(
            entity_id=group.id,
            entity_type="intrusion-set",
            alias="Analyst Name",
            alias_norm="analyst name",
            source="analyst",
        )
    )
    # alias analyst yang sama dengan alias resmi baru: tetap analyst, tidak ditimpa
    await async_db_session.execute(
        EntityAlias.__table__.update()
        .where(EntityAlias.entity_id == group.id, EntityAlias.alias_norm == "group alias")
        .values(source="analyst")
    )
    await async_db_session.flush()

    await upsert_attack_entities(async_db_session, _bundle())

    rows = dict(
        (
            await async_db_session.execute(
                select(EntityAlias.alias_norm, EntityAlias.source).where(
                    EntityAlias.entity_id == group.id
                )
            )
        ).all()
    )
    assert rows["analyst name"] == "analyst"
    assert rows["group alias"] == "analyst"
    assert rows["test group"] == "attack"


async def test_sync_renamed_group_updates_name(async_db_session: AsyncSession) -> None:
    await upsert_attack_entities(async_db_session, _bundle())
    renamed = copy.deepcopy(_bundle())
    renamed[0]["name"] = "Renamed Group"
    renamed[0]["aliases"] = ["Renamed Group", "Group Alias"]

    await upsert_attack_entities(async_db_session, renamed)

    group = await _entity(async_db_session, GROUP)
    assert group
    await async_db_session.refresh(group)
    assert group.name == "Renamed Group"
    norms = set(
        (
            await async_db_session.execute(
                select(EntityAlias.alias_norm).where(EntityAlias.entity_id == group.id)
            )
        ).scalars()
    )
    assert "renamed group" in norms  # nama baru jadi alias; alias lama tidak dibuang


async def test_sync_skips_revoked_without_deleting(async_db_session: AsyncSession) -> None:
    await upsert_attack_entities(async_db_session, _bundle())
    revoked = copy.deepcopy(_bundle())
    revoked[3]["revoked"] = True  # campaign kini revoked

    await upsert_attack_entities(async_db_session, revoked)

    assert await _entity(async_db_session, CAMPAIGN) is not None


async def test_sync_domain_calls_entity_upsert(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = {"type": "bundle", "objects": _bundle()}
    real = httpx.AsyncClient

    def _client(**kw: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=bundle)), **kw)

    monkeypatch.setattr(attack_mod.httpx, "AsyncClient", _client)

    result = await AsyncAttackSyncRepo(async_db_session).sync_domain("enterprise")

    assert result["status"] == "success"
    assert await _entity(async_db_session, CAMPAIGN) is not None


def _ent(type_: str, name: str, source: str, **kw: Any) -> Entity:
    return Entity(type=type_, name=name, source=source, stix_id=f"{type_}--legacy-{name}", **kw)


async def _snapshot(session: AsyncSession, stix_id: str) -> tuple[Any, ...]:
    e = await _entity(session, stix_id)
    assert e
    await session.refresh(e)
    return (e.type, e.name, e.external_id, e.source, e.stix_id)


@pytest.mark.parametrize("old_source", ["dictionary", "legacy"])
async def test_sync_adopts_existing_entity(async_db_session: AsyncSession, old_source: str) -> None:
    s = async_db_session
    old = _ent("intrusion-set", "test group", old_source, description=None)
    s.add(old)
    await s.flush()
    s.add(
        EntityAlias(
            entity_id=old.id,
            entity_type="intrusion-set",
            alias="Mine",
            alias_norm="mine",
            source="analyst",
        )
    )
    art = Article(url="http://a/1", url_hash="adopt-1", title="t", source="src")
    s.add(art)
    await s.flush()
    s.add(
        EntityMention(
            article_id=art.id, entity_id=old.id, method="dictionary", matched_alias="test group"
        )
    )
    await s.flush()
    old_id = old.id

    await upsert_attack_entities(s, _bundle())

    got = await _entity(s, GROUP)
    assert got and got.id == old_id
    await s.refresh(got)
    assert (got.source, got.name, got.external_id, got.description) == (
        "attack",
        "Test Group",
        "G9001",
        "grup uji",  # kosong -> diisi ATT&CK (Ruling 27)
    )
    norms = {
        (n, src)
        for n, src in (
            await s.execute(
                select(EntityAlias.alias_norm, EntityAlias.source).where(
                    EntityAlias.entity_id == old_id
                )
            )
        ).all()
    }
    assert ("mine", "analyst") in norms and ("group alias", "attack") in norms
    n_ment = (
        await s.execute(select(EntityMention.id).where(EntityMention.entity_id == old_id))
    ).all()
    assert len(n_ment) == 1
    assert (
        await s.execute(
            select(Entity.id).where(Entity.type == "intrusion-set", Entity.name.ilike("test group"))
        )
    ).all() == [(old_id,)]


async def test_adopted_equals_fresh_insert(async_db_session: AsyncSession) -> None:
    s = async_db_session
    await upsert_attack_entities(s, _bundle())
    fresh = await _snapshot(s, MALWARE)
    # entitas lama dengan nama sama tapi huruf kecil, deskripsi sudah terisi (tidak ditimpa)
    other = copy.deepcopy(_bundle())
    other[1]["id"] = "malware--99999999-9999-4999-8999-999999999999"
    other[1]["name"] = "OtherMal"
    other[1]["x-mitre-aliases"] = ["OtherMal"]
    other[1]["external_references"] = _ext("S9009")
    s.add(_ent("malware", "othermal", "dictionary", description="punya analis"))
    await s.flush()
    await upsert_attack_entities(s, other)
    adopted = await _snapshot(s, other[1]["id"])
    assert adopted[1:3] == ("OtherMal", "S9009") and adopted[3] == "attack"
    ent = await _entity(s, other[1]["id"])
    assert ent and ent.description == "punya analis"
    assert fresh[0] == adopted[0] == "malware"


async def test_sync_adopts_legacy_technique_by_id(async_db_session: AsyncSession) -> None:
    s = async_db_session
    old = Entity(
        type="attack-pattern",
        name="Old name",
        source="legacy",
        stix_id="attack-pattern--legacy-1",
        external_id="T9001.001",
    )
    s.add(old)
    await s.flush()
    old_id = old.id

    await upsert_attack_entities(s, _bundle())

    tech = await _entity(s, TECH)
    assert tech and tech.id == old_id
    await s.refresh(tech)
    assert (tech.name, tech.source) == ("Spearphishing Attachment", "attack")


async def test_alias_collision_own_name_wins_any_order(async_db_session: AsyncSession) -> None:
    a = {
        "type": "intrusion-set",
        "id": "intrusion-set--aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "name": "Zed",
        "aliases": ["Zed", "xray"],
        "external_references": _ext("G9101"),
    }
    b = {
        "type": "intrusion-set",
        "id": "intrusion-set--bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "name": "Xray",
        "aliases": ["Xray"],
        "external_references": _ext("G9102"),
    }
    await upsert_attack_entities(async_db_session, [a, b])  # A lebih kecil, daftar alias "xray"
    owner = (
        await async_db_session.execute(
            select(Entity.stix_id)
            .join(EntityAlias, EntityAlias.entity_id == Entity.id)
            .where(EntityAlias.entity_type == "intrusion-set", EntityAlias.alias_norm == "xray")
        )
    ).scalar_one()
    assert owner == b["id"]


async def test_group_without_external_id_is_created(async_db_session: AsyncSession) -> None:
    obj = {"type": "intrusion-set", "id": "intrusion-set--no-ext", "name": "No Ext Group"}
    await upsert_attack_entities(async_db_session, [obj])
    e = await _entity(async_db_session, "intrusion-set--no-ext")
    assert e and e.external_id is None


async def test_rename_collision_keeps_old_name(async_db_session: AsyncSession) -> None:
    s = async_db_session
    await upsert_attack_entities(s, _bundle())
    other = {
        "type": "intrusion-set",
        "id": "intrusion-set--cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "name": "Other Group",
        "external_references": _ext("G9201"),
    }
    await upsert_attack_entities(s, [other])
    clash = {**other, "name": "TEST GROUP"}  # bentrok dengan Test Group
    await upsert_attack_entities(s, [clash])  # tidak boleh melempar
    e = await _entity(s, other["id"])
    assert e
    await s.refresh(e)
    assert e.name == "Other Group"


async def test_relationship_end_follows_merged_tombstone(async_db_session: AsyncSession) -> None:
    s = async_db_session
    await upsert_attack_entities(s, _bundle())
    live = Entity(type="malware", name="Live Mal", source="analyst", stix_id="malware--live-1")
    s.add(live)
    await s.flush()
    mal = await _entity(s, MALWARE)
    assert mal
    mal.merged_into_id = live.id
    await s.flush()
    extra = [_rel(8, "uses", GROUP, MALWARE)]
    extra[0]["id"] = "relationship--00000008-0000-4000-8000-00000000000a"

    await upsert_attack_entities(s, extra)

    group = await _entity(s, GROUP)
    assert group
    tgt = (
        await s.execute(
            select(Relationship.target_entity_id).where(Relationship.stix_id == extra[0]["id"])
        )
    ).scalar_one()
    assert tgt == live.id
