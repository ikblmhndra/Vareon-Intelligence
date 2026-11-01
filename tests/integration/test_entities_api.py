"""API entitas P7c (`/api/entities`, `/api/relationships`, spec 5.2) lewat HTTP ke Postgres NYATA.

Yang dijaga: filter daftar (tipe, alias `q`, suppressed/merged, kursor, hitungan mention 30/90
hari), detail tombstone membawa `merged_into_id`, co-mention (jendela 365 hari, pasangan yang
sudah punya relasi hidup dibuang), semua penulisan meninggalkan baris audit, 409 untuk alias
milik entitas lain / merge lintas tipe / split tanpa alias nama sendiri (Ruling 17), watch per
klien, permission (`manage_entities` untuk analyst, 403 untuk role tanpa itu), dan profil LLM
memakai fungsi LLM `ta_profile` (di-mock)."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

import pytest
from cti_api import deps
from cti_api.services.roles import ensure_system_roles
from cti_core.db.models.article import Article
from cti_core.db.models.attack import AttackMitigation, AttackRelationship, AttackTechnique
from cti_core.db.models.auth import AuditLogEntry, Client
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
from cti_core.db.repositories.auth import AsyncRoleRepo
from cti_core.entity import alias_norm
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

Header = Callable[..., dict[str, str]]


@pytest.fixture(autouse=True)
def _fresh_permission_cache() -> None:
    deps.invalidate_role_permissions()


async def _make(s: AsyncSession, type_: str, name: str, *aliases: str, **kw: Any) -> Entity:
    e = Entity(type=type_, stix_id=f"{type_}--t13-{name}", name=name, source="analyst", **kw)
    s.add(e)
    await s.flush()
    for a in (kw.get("external_id") if type_ == "attack-pattern" else name, *aliases):
        s.add(
            EntityAlias(
                entity_id=e.id,
                entity_type=type_,
                alias=a,
                alias_norm=alias_norm(a),
                source="galaxy",
            )
        )
    await s.flush()
    return e


_n = 0


async def _article(s: AsyncSession, *, days_ago: int = 0, story: Story | None = None) -> Article:
    global _n
    _n += 1
    posted = datetime.datetime.now(datetime.UTC).date() - datetime.timedelta(days=days_ago)
    a = Article(
        url=f"http://t13/{_n}",
        url_hash=f"t13-{_n}",
        title=f"article {_n}",
        source="src",
        posted_on=posted,
        story_id=None if story is None else story.id,
    )
    s.add(a)
    await s.flush()
    return a


async def _story(s: AsyncSession, title: str) -> Story:
    st = Story(title=title, lead_source="src")
    s.add(st)
    await s.flush()
    return st


async def _mention(s: AsyncSession, e: Entity, article: Article) -> None:
    s.add(
        EntityMention(
            article_id=article.id, entity_id=e.id, method="dictionary", matched_alias=e.name
        )
    )
    await s.flush()


async def _audit(s: AsyncSession, action: str) -> list[AuditLogEntry]:
    return list(
        (await s.scalars(select(AuditLogEntry).where(AuditLogEntry.action == action))).all()
    )


async def test_list_filters_by_type_alias_and_counts(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    panda = await _make(s, "intrusion-set", "Zeta Panda", "Zeta Bear")
    loader = await _make(s, "malware", "ZetaLoader")
    hidden = await _make(s, "intrusion-set", "Zeta Hidden", suppressed=True)
    gone = await _make(s, "intrusion-set", "Zeta Gone")
    gone.merged_into_id = panda.id
    await _mention(s, panda, await _article(s, days_ago=1))
    await _mention(s, panda, await _article(s, days_ago=60))
    await _mention(s, panda, await _article(s, days_ago=200))
    await s.commit()
    h = auth_header()

    r = await api_client.get(
        "/api/entities", params={"type": "intrusion-set", "q": "zeta  BEAR"}, headers=h
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["id"] for i in items] == [panda.id]
    item = items[0]
    assert set(item["aliases"]) == {"Zeta Panda", "Zeta Bear"}
    assert (item["mentions_30d"], item["mentions_90d"]) == (1, 2)
    assert item["watched"] is False
    assert item["suppressed"] is False

    r = await api_client.get("/api/entities", params={"q": "zeta"}, headers=h)
    assert {i["id"] for i in r.json()["items"]} == {panda.id, loader.id}

    r = await api_client.get(
        "/api/entities", params={"q": "zeta", "include_suppressed": True}, headers=h
    )
    assert {i["id"] for i in r.json()["items"]} == {panda.id, loader.id, hidden.id}

    # kursor: urut nama, halaman kedua melanjutkan tanpa duplikat
    page1 = (
        await api_client.get("/api/entities", params={"q": "zeta", "limit": 1}, headers=h)
    ).json()
    assert [i["id"] for i in page1["items"]] == [panda.id]  # "zeta panda" < "zetaloader"
    assert page1["next_cursor"]
    page2 = (
        await api_client.get(
            "/api/entities",
            params={"q": "zeta", "limit": 1, "cursor": page1["next_cursor"]},
            headers=h,
        )
    ).json()
    assert [i["id"] for i in page2["items"]] == [loader.id]
    assert page2["next_cursor"] is None

    bad = await api_client.get("/api/entities", params={"cursor": "!!nope"}, headers=h)
    assert bad.status_code == 422


async def test_detail_of_merged_entity_returns_merged_into_id(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    target = await _make(s, "intrusion-set", "Detail Target", "DT-1")
    tomb = await _make(s, "intrusion-set", "Detail Tomb")
    tomb.merged_into_id = target.id
    await s.commit()

    r = await api_client.get(f"/api/entities/{tomb.id}", headers=auth_header())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == tomb.id
    assert body["merged_into_id"] == target.id

    r = await api_client.get(f"/api/entities/{target.id}", headers=auth_header())
    body = r.json()
    assert body["merged_into_id"] is None
    assert {a["alias"] for a in body["aliases"]} == {"Detail Target", "DT-1"}
    assert all({"id", "alias", "source"} <= set(a) for a in body["aliases"])
    assert (
        await api_client.get("/api/entities/99999999", headers=auth_header())
    ).status_code == 404


async def test_co_mentions_exclude_related_pairs_and_old_stories(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    e = await _make(s, "intrusion-set", "Co Actor")
    f = await _make(s, "malware", "Co Malware")
    g = await _make(s, "tool", "Co Tool")
    old = await _make(s, "malware", "Co Old")
    quiet = await _make(s, "malware", "Co Suppressed", suppressed=True)
    recent = await _story(s, "recent")
    await _mention(s, e, await _article(s, days_ago=3, story=recent))
    member = await _article(s, days_ago=2, story=recent)
    for x in (f, g, quiet):
        await _mention(s, x, member)
    # story-less article: dihitung sebagai story sendiri
    solo = await _article(s, days_ago=5)
    await _mention(s, e, solo)
    await _mention(s, f, solo)
    stale = await _story(s, "stale")
    await _mention(s, e, await _article(s, days_ago=400, story=stale))
    await _mention(s, old, await _article(s, days_ago=400, story=stale))
    s.add(
        Relationship(
            stix_id="relationship--t13-co",
            relationship_type="uses",
            source_entity_id=g.id,
            target_entity_id=e.id,
            provenance="analyst",
        )
    )
    s.add(
        Relationship(
            stix_id="relationship--t13-co-revoked",
            relationship_type="uses",
            source_entity_id=e.id,
            target_entity_id=f.id,
            provenance="analyst",
            revoked_at=datetime.datetime.now(datetime.UTC),
        )
    )
    await s.commit()

    r = await api_client.get(f"/api/entities/{e.id}/relationships", headers=auth_header())
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(c["entity"]["id"], c["stories"]) for c in body["co_mentions"]] == [(f.id, 2)]
    rels = body["relationships"]
    assert [(x["source"]["id"], x["relationship_type"], x["target"]["id"]) for x in rels] == [
        (g.id, "uses", e.id)
    ]


async def test_entity_writes_and_audit(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    h = auth_header(username="ana")
    other = await _make(s, "intrusion-set", "Owner Actor", "Shared Name")
    await s.commit()
    other_id = other.id  # sesudah 409 router me-rollback sesi bersama -> objek kedaluwarsa

    r = await api_client.post(
        "/api/entities",
        json={
            "type": "intrusion-set",
            "name": "New Actor",
            "aliases": ["NA Group"],
            "description": "d",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["source"] == "analyst"
    assert {a["alias"] for a in new["aliases"]} == {"New Actor", "NA Group"}
    assert (await _audit(s, "entity_create"))[-1].username == "ana"

    dup = await api_client.post(
        "/api/entities", json={"type": "intrusion-set", "name": "shared  name"}, headers=h
    )
    assert dup.status_code == 409
    assert "detail" in dup.json()

    # alias
    r = await api_client.post(
        f"/api/entities/{new['id']}/aliases", json={"alias": "NA Crew"}, headers=h
    )
    assert r.status_code == 201, r.text
    alias_id = r.json()["id"]
    taken = await api_client.post(
        f"/api/entities/{new['id']}/aliases", json={"alias": "SHARED name"}, headers=h
    )
    assert taken.status_code == 409
    assert str(other_id) in taken.json()["detail"]
    r = await api_client.delete(f"/api/entities/{new['id']}/aliases/{alias_id}", headers=h)
    assert r.status_code == 200, r.text
    own = next(a["id"] for a in new["aliases"] if a["alias"] == "New Actor")
    assert (
        await api_client.delete(f"/api/entities/{new['id']}/aliases/{own}", headers=h)
    ).status_code == 409
    assert await _audit(s, "entity_alias_add")
    assert await _audit(s, "entity_alias_remove")

    # patch
    r = await api_client.patch(
        f"/api/entities/{new['id']}",
        json={"name": "New Actor Renamed", "description": "d2"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "New Actor Renamed"
    assert "New Actor Renamed" in {a["alias"] for a in r.json()["aliases"]}
    assert await _audit(s, "entity_update")
    r = await api_client.patch(f"/api/entities/{new['id']}", json={"suppressed": True}, headers=h)
    assert r.json()["suppressed"] is True
    assert (await _audit(s, "entity_suppress"))[-1].username == "ana"
    await api_client.patch(f"/api/entities/{new['id']}", json={"suppressed": False}, headers=h)

    # merge: lintas tipe 409, preview, merge, split (revive)
    mal_id = (await _make(s, "malware", "Some Malware")).id
    await s.commit()
    cross = await api_client.post(
        f"/api/entities/{new['id']}/merge", json={"into_id": mal_id}, headers=h
    )
    assert cross.status_code == 409
    assert "detail" in cross.json()
    preview = await api_client.get(
        f"/api/entities/{new['id']}/merge-preview", params={"into_id": other_id}, headers=h
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["moved_aliases"] == 3  # New Actor, NA Group, New Actor Renamed
    assert (await s.get(Entity, new["id"])).merged_into_id is None  # type: ignore[union-attr]
    r = await api_client.post(
        f"/api/entities/{new['id']}/merge", json={"into_id": other_id}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json() == preview.json()
    assert (await _audit(s, "entity_merge"))[-1].username == "ana"

    detail = (await api_client.get(f"/api/entities/{other_id}", headers=h)).json()
    moved = [a["id"] for a in detail["aliases"] if a["alias"] in ("NA Group", "New Actor")]
    no_own = await api_client.post(
        f"/api/entities/{other_id}/split", json={"alias_ids": moved}, headers=h
    )
    assert no_own.status_code == 409
    assert "own name alias" in no_own.json()["detail"]  # Ruling 17
    all_ids = [
        a["id"]
        for a in detail["aliases"]
        if a["alias"] in ("New Actor", "NA Group", "New Actor Renamed")
    ]
    r = await api_client.post(
        f"/api/entities/{other_id}/split", json={"alias_ids": all_ids}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == new["id"]
    assert r.json()["merged_into_id"] is None
    assert (await _audit(s, "entity_split"))[-1].username == "ana"


async def test_relationship_create_duplicate_revoke_unrevoke(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    h = auth_header(username="rel")
    a = await _make(s, "intrusion-set", "Rel Actor")
    b = await _make(s, "malware", "Rel Malware")
    dead = await _make(s, "malware", "Rel Dead", suppressed=True)
    await s.commit()
    dead_id = dead.id
    body = {"source_id": a.id, "relationship_type": "uses", "target_id": b.id}

    r = await api_client.post("/api/relationships", json=body, headers=h)
    assert r.status_code == 201, r.text
    rel = r.json()
    assert (rel["confidence"], rel["provenance"], rel["created_by"]) == (75, "analyst", "rel")
    assert rel["stix_id"].startswith("relationship--")
    assert (await _audit(s, "relationship_create"))[-1].username == "rel"

    assert (await api_client.post("/api/relationships", json=body, headers=h)).status_code == 409
    bad_type = {**body, "relationship_type": "loves"}
    assert (
        await api_client.post("/api/relationships", json=bad_type, headers=h)
    ).status_code == 422
    to_dead = {**body, "target_id": dead_id}
    assert (await api_client.post("/api/relationships", json=to_dead, headers=h)).status_code == 409

    r = await api_client.delete(f"/api/relationships/{rel['id']}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["revoked_at"] is not None
    assert r.json()["revoked_by"] == "rel"
    again = await api_client.delete(f"/api/relationships/{rel['id']}", headers=h)
    assert again.status_code == 200
    assert again.json()["revoked_at"] == r.json()["revoked_at"]
    assert len(await _audit(s, "relationship_revoke")) == 1

    r = await api_client.post("/api/relationships", json={**body, "confidence": 40}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["id"] == rel["id"]
    assert r.json()["revoked_at"] is None
    assert r.json()["confidence"] == 40
    assert (await api_client.delete("/api/relationships/99999999", headers=h)).status_code == 404


async def test_watch_is_per_client(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    await s.merge(Client(client_id="other", name="Other"))
    e = await _make(s, "intrusion-set", "Watch Actor")
    await s.commit()
    h = auth_header(client_ids=["default", "other"])
    default = {**h, "X-Client-ID": "default"}
    other = {**h, "X-Client-ID": "other"}

    r = await api_client.put(f"/api/entities/{e.id}/watch", headers=default)
    assert r.status_code == 200, r.text
    assert r.json() == {"watched": True}
    assert (await api_client.put(f"/api/entities/{e.id}/watch", headers=default)).status_code == 200
    rows = (await s.scalars(select(EntityWatch).where(EntityWatch.entity_id == e.id))).all()
    assert [w.client_id for w in rows] == ["default"]
    assert await _audit(s, "entity_watch")

    params = {"watched": True, "q": "watch actor"}
    mine = await api_client.get("/api/entities", params=params, headers=default)
    assert [i["id"] for i in mine.json()["items"]] == [e.id]
    assert mine.json()["items"][0]["watched"] is True
    theirs = await api_client.get("/api/entities", params=params, headers=other)
    assert theirs.json()["items"] == []
    assert (await api_client.get(f"/api/entities/{e.id}", headers=other)).json()["watched"] is False

    r = await api_client.delete(f"/api/entities/{e.id}/watch", headers=default)
    assert r.json() == {"watched": False}
    assert await _audit(s, "entity_unwatch")


async def test_analyst_can_merge_and_role_without_permission_gets_403(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    await ensure_system_roles(s)
    await AsyncRoleRepo(s).create(
        name="t13-viewer", display_name="Viewer", permissions=["view_ta"], created_by="t"
    )
    a = await _make(s, "malware", "Perm Src")
    b = await _make(s, "malware", "Perm Dst")
    await s.commit()

    viewer = auth_header(username="vic", role="t13-viewer")
    assert (await api_client.get("/api/entities", headers=viewer)).status_code == 200
    for method, path, body in (
        ("POST", "/api/entities", {"type": "malware", "name": "x"}),
        ("POST", f"/api/entities/{a.id}/merge", {"into_id": b.id}),
        ("POST", "/api/relationships", {}),
        ("PUT", f"/api/entities/{a.id}/watch", None),
        ("POST", f"/api/entities/{a.id}/profile", None),
    ):
        r = await api_client.request(method, path, json=body, headers=viewer)
        assert r.status_code == 403, (method, path, r.text)

    analyst = auth_header(username="alice", role="analyst")
    r = await api_client.post(
        f"/api/entities/{a.id}/merge", json={"into_id": b.id}, headers=analyst
    )
    assert r.status_code == 200, r.text
    assert (
        await api_client.post(f"/api/entities/{b.id}/profile", headers=analyst)
    ).status_code == 403  # manage_intel


async def test_profile_uses_ta_profile_llm_function(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Header,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = api_session
    actor = await _make(s, "intrusion-set", "Profile Actor")
    mal = await _make(s, "malware", "Profile Malware")
    await s.commit()
    calls: list[str] = []

    def fake_llm(user_msg: str) -> dict[str, Any]:
        calls.append(user_msg)
        return {"identity": {"primary_name": "Profile Actor"}}

    monkeypatch.setattr("cti_api.services.ta_profile._call_llm", fake_llm)
    h = auth_header(username="prof")
    r = await api_client.post(f"/api/entities/{actor.id}/profile", headers=h)
    assert r.status_code == 200, r.text
    assert len(calls) == 1
    assert "Threat actor: Profile Actor" in calls[0]
    assert r.json()["profile"]["identity"]["primary_name"] == "Profile Actor"
    row = await s.scalar(select(EntityProfile).where(EntityProfile.entity_id == actor.id))
    assert row is not None
    assert (await _audit(s, "entity_profile_generate"))[-1].username == "prof"
    detail = (await api_client.get(f"/api/entities/{actor.id}", headers=h)).json()
    assert detail["profile"]["identity"]["primary_name"] == "Profile Actor"

    r = await api_client.post(f"/api/entities/{mal.id}/profile", headers=h)
    assert r.status_code == 409
    assert len(calls) == 1


async def test_attack_endpoint_techniques_mitigations_layer(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    actor = await _make(s, "intrusion-set", "Attack Actor")
    tech = await _make(s, "attack-pattern", "Phish Test", external_id="T9901")
    s.add(
        AttackTechnique(
            stix_id="attack-pattern--t13",
            attack_id="T9901",
            name="Phish Test",
            tactics=["initial-access"],
        )
    )
    s.add(AttackMitigation(stix_id="course-of-action--t13", mitigation_id="M9901", name="Train"))
    s.add(
        AttackRelationship(
            stix_id="relationship--t13-mit",
            relationship_type="mitigates",
            source_ref="course-of-action--t13",
            source_type="course-of-action",
            target_ref="attack-pattern--t13",
            target_type="attack-pattern",
            domain="enterprise-attack",
        )
    )
    s.add(
        Relationship(
            stix_id="relationship--t13-uses",
            relationship_type="uses",
            source_entity_id=actor.id,
            target_entity_id=tech.id,
            provenance="attack",
        )
    )
    await s.commit()

    r = await api_client.get(f"/api/entities/{actor.id}/attack", headers=auth_header())
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(t["external_id"], t["tactics"]) for t in body["techniques"]] == [
        ("T9901", ["initial-access"])
    ]
    assert [(m["mitigation_id"], m["techniques"]) for m in body["mitigations"]] == [
        ("M9901", ["T9901"])
    ]
    assert [t["techniqueID"] for t in body["layer"]["techniques"]] == ["T9901"]

    own = (await api_client.get(f"/api/entities/{tech.id}/attack", headers=auth_header())).json()
    assert [t["external_id"] for t in own["techniques"]] == ["T9901"]


async def test_stories_indicators_cves_timeline(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    e = await _make(s, "intrusion-set", "Read Actor")
    st = await _story(s, "Read story")
    await _mention(s, e, await _article(s, days_ago=1, story=st))
    await _mention(s, e, await _article(s, days_ago=2, story=st))
    ind = Indicator(type="domain", value="t13.example")
    s.add(ind)
    await s.flush()
    s.add(EntityMention(indicator_id=ind.id, entity_id=e.id, method="analyst", matched_alias="x"))
    await s.commit()
    h = auth_header()

    r = await api_client.get(f"/api/entities/{e.id}/stories", headers=h)
    assert r.status_code == 200, r.text
    assert [(i["id"], i["mentioned_articles"]) for i in r.json()["items"]] == [(st.id, 2)]
    r = await api_client.get(f"/api/entities/{e.id}/indicators", headers=h)
    assert [i["value"] for i in r.json()["items"]] == ["t13.example"]
    r = await api_client.get(f"/api/entities/{e.id}/cves", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []
    r = await api_client.get(f"/api/entities/{e.id}/timeline", params={"months": 3}, headers=h)
    assert r.status_code == 200, r.text
    months = r.json()["months"]
    assert len(months) == 3
    assert sum(m["articles"] for m in months) == 2


async def test_integrity_error_race_returns_409(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Header,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling 29: request lain menulis di antara cek service dan INSERT -> indeks unik menolak;
    hasilnya 409 dengan detail netral, bukan 500. Balapan dipaksa dengan melewati cek service."""
    s = api_session
    await _make(s, "intrusion-set", "Race Actor")
    await s.commit()

    async def _free(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("cti_api.services.entities._check_alias_free", _free)
    monkeypatch.setattr("cti_api.services.entities._check_name_free", _free)
    r = await api_client.post(
        "/api/entities", json={"type": "intrusion-set", "name": "race actor"}, headers=auth_header()
    )
    assert r.status_code == 409, r.text
    assert r.json() == {"detail": "conflicting change, reload and try again"}


async def test_create_external_id_conflicts_and_alias_length(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    cve_id = (await _make(s, "vulnerability", "CVE-2099-0101", external_id="CVE-2099-0101")).id
    sw_id = (await _make(s, "malware", "Ext Malware", external_id="S9901")).id
    await s.commit()
    h = auth_header()

    # id CVE huruf kecil dinormalisasi ke huruf besar lalu bentrok dengan entitas yang ada
    r = await api_client.post(
        "/api/entities",
        json={"type": "vulnerability", "name": "Other CVE label", "external_id": "cve-2099-0101"},
        headers=h,
    )
    assert r.status_code == 409, r.text
    assert str(cve_id) in r.json()["detail"]
    r = await api_client.post(
        "/api/entities",
        json={"type": "malware", "name": "Other Malware", "external_id": "S9901"},
        headers=h,
    )
    assert r.status_code == 409, r.text
    assert str(sw_id) in r.json()["detail"]

    r = await api_client.post(
        "/api/entities",
        json={"type": "vulnerability", "name": "New CVE", "external_id": "cve-2099-0102"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["external_id"] == "CVE-2099-0102"

    long_alias = await api_client.post(
        "/api/entities",
        json={"type": "malware", "name": "Long Alias Malware", "aliases": ["x" * 301]},
        headers=h,
    )
    assert long_alias.status_code == 422
    empty_alias = await api_client.post(
        "/api/entities",
        json={"type": "malware", "name": "Empty Alias Malware", "aliases": [""]},
        headers=h,
    )
    assert empty_alias.status_code == 422


async def test_merge_rejections(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    a = await _make(s, "tool", "Rej A")
    b = await _make(s, "tool", "Rej B")
    tomb = await _make(s, "tool", "Rej Tomb")
    tomb.merged_into_id = b.id
    hidden = await _make(s, "tool", "Rej Hidden", suppressed=True)
    await s.commit()
    a_id, tomb_id, hidden_id = a.id, tomb.id, hidden.id
    h = auth_header()

    for src, dst, needle in (
        (a_id, a_id, "itself"),
        (tomb_id, a_id, "already merged"),
        (a_id, tomb_id, "already merged"),
        (a_id, hidden_id, "suppressed"),  # Ruling 30
        (hidden_id, a_id, "suppressed"),
    ):
        r = await api_client.post(f"/api/entities/{src}/merge", json={"into_id": dst}, headers=h)
        assert r.status_code == 409, (src, dst, r.text)
        assert needle in r.json()["detail"], (src, dst, r.json())
    r = await api_client.get(
        f"/api/entities/{a_id}/merge-preview", params={"into_id": hidden_id}, headers=h
    )
    assert r.status_code == 409


async def test_watch_with_unassigned_client_header_is_403(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    await s.merge(Client(client_id="other", name="Other"))
    e = await _make(s, "intrusion-set", "Foreign Watch Actor")
    await s.commit()
    e_id = e.id
    analyst = auth_header(username="alice", role="analyst", client_ids=["default"])
    await ensure_system_roles(s)
    await s.commit()

    r = await api_client.put(
        f"/api/entities/{e_id}/watch", headers={**analyst, "X-Client-ID": "other"}
    )
    assert r.status_code == 403, r.text
    rows = (await s.scalars(select(EntityWatch).where(EntityWatch.entity_id == e_id))).all()
    assert rows == []


async def test_cursor_uses_sql_sort_key_for_non_ascii_names(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    """Kursor menyimpan lower() Postgres dari baris itu sendiri: dengan str.lower() Python, nama
    non-ASCII ("Éclair") bisa melompati baris berikutnya bila lower() server berbeda."""
    s = api_session
    first = await _make(s, "campaign", "Éclair Op A")
    second = await _make(s, "campaign", "Éclair Op B")
    await s.commit()
    ids = [first.id, second.id]
    h = auth_header()
    params: dict[str, Any] = {"type": "campaign", "q": "clair op", "limit": 1}

    seen: list[int] = []
    cursor = None
    for _ in range(3):
        page = (
            await api_client.get(
                "/api/entities",
                params={**params, **({"cursor": cursor} if cursor else {})},
                headers=h,
            )
        ).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == ids


async def test_list_type_comma_list(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    mal = await _make(s, "malware", "CommaLoader")
    tool = await _make(s, "tool", "CommaTool")
    await _make(s, "intrusion-set", "CommaActor")
    await s.commit()
    r = await api_client.get(
        "/api/entities", params={"type": "malware,tool", "q": "comma"}, headers=auth_header()
    )
    assert r.status_code == 200, r.text
    assert {i["id"] for i in r.json()["items"]} == {mal.id, tool.id}
    bad = await api_client.get(
        "/api/entities", params={"type": "malware,nope"}, headers=auth_header()
    )
    assert bad.status_code == 422


async def test_list_identity_class(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    await _make(s, "identity", "Banking Sector", identity_class="class")
    victim = await _make(s, "identity", "Bank Victim Ltd", identity_class="organization")
    await s.commit()
    r = await api_client.get(
        "/api/entities",
        params={"type": "identity", "identity_class": "organization"},
        headers=auth_header(),
    )
    assert r.status_code == 200, r.text
    assert [i["id"] for i in r.json()["items"]] == [victim.id]


async def _resolve(api_client: AsyncClient, h: dict[str, str], type_: str, name: str) -> Any:
    return await api_client.get(
        "/api/entities/resolve", params={"type": type_, "name": name}, headers=h
    )


async def test_resolve_by_alias(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    apt29 = await _make(api_session, "intrusion-set", "APT29", "Cozy Bear")
    await api_session.commit()
    r = await _resolve(api_client, auth_header(), "intrusion-set", "cozy  BEAR")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "id": apt29.id,
        "name": "APT29",
        "type": "intrusion-set",
        "external_id": None,
    }


async def test_resolve_follows_merge(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    apt29 = await _make(api_session, "intrusion-set", "APT29")
    duke = await _make(api_session, "intrusion-set", "Cozy Duke")
    await api_session.commit()
    h = auth_header()
    m = await api_client.post(
        f"/api/entities/{duke.id}/merge", json={"into_id": apt29.id}, headers=h
    )
    assert m.status_code == 200, m.text
    r = await _resolve(api_client, h, "intrusion-set", "Cozy Duke")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == apt29.id


async def test_resolve_external_id(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    tech = await _make(s, "attack-pattern", "Phishing", external_id="T1566")
    cve = await _make(s, "vulnerability", "Palo Alto PAN-OS Bug", external_id="CVE-2024-3400")
    await s.commit()
    h = auth_header()
    r = await _resolve(api_client, h, "attack-pattern", "t1566")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == tech.id
    r = await _resolve(api_client, h, "vulnerability", "cve-2024-3400")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == cve.id


async def test_resolve_country_code(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    # Indonesia sudah di-seed (bootstrap lokasi); pastikan bentuknya, jangan buat ulang
    indo = (
        await api_session.scalars(
            select(Entity).where(Entity.type == "location", Entity.external_id == "ID")
        )
    ).one()
    assert indo.name == "Indonesia"
    r = await _resolve(api_client, auth_header(), "location", "id")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == indo.id


async def test_resolve_special_chars(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    play = await _make(api_session, "intrusion-set", "#play")
    await api_session.commit()
    r = await api_client.get(
        "/api/entities/resolve?type=intrusion-set&name=%23play", headers=auth_header()
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == play.id


async def test_resolve_unknown_404(api_client: AsyncClient, auth_header: Header) -> None:
    r = await _resolve(api_client, auth_header(), "intrusion-set", "nope")
    assert r.status_code == 404
    assert r.json() == {"detail": "no entity named nope"}
    bad = await _resolve(api_client, auth_header(), "bogus", "nope")
    assert bad.status_code == 422


async def test_resolve_suppressed_still_resolves(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    hid = await _make(api_session, "intrusion-set", "Hidden Actor", suppressed=True)
    await api_session.commit()
    r = await _resolve(api_client, auth_header(), "intrusion-set", "hidden actor")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == hid.id


async def test_detail_merged_from(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    apt29 = await _make(api_session, "intrusion-set", "APT29")
    duke = await _make(api_session, "intrusion-set", "Cozy Duke")
    await api_session.commit()
    h = auth_header()
    assert (await api_client.get(f"/api/entities/{apt29.id}", headers=h)).json()[
        "merged_from"
    ] == []
    await api_client.post(f"/api/entities/{duke.id}/merge", json={"into_id": apt29.id}, headers=h)
    body = (await api_client.get(f"/api/entities/{apt29.id}", headers=h)).json()
    assert body["merged_from"] == [
        {"id": duke.id, "name": "Cozy Duke", "type": "intrusion-set", "external_id": None}
    ]
    own = [a["id"] for a in body["aliases"] if a["alias"] == "Cozy Duke"]
    r = await api_client.post(f"/api/entities/{apt29.id}/split", json={"alias_ids": own}, headers=h)
    assert r.status_code == 200, r.text
    body = (await api_client.get(f"/api/entities/{apt29.id}", headers=h)).json()
    assert body["merged_from"] == []
