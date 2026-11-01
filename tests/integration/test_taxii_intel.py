"""Koleksi TAXII `intel` dan feed REST `/api/v2/entities`, `/api/v2/relationships` (P7c Task 15):
graf entitas + relasi + report + indikator, TLP per token, ref-integrity, scope `intel:read`."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from cti_api import machine_auth
from cti_api.routers.taxii import COLLECTION_ID, INTEL_COLLECTION_ID, TAXII_MEDIA
from cti_api.services import feed
from cti_core.db.models.entity import Entity
from cti_core.db.models.indicator import Indicator
from cti_core.db.repositories.auth import AsyncApiTokenRepo
from cti_core.indicator.stix_id import indicator_uuid
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration import intel_support
from tests.integration.intel_support import (
    AFTER,
    CLEAR_ORDER,
    RED_ORDER,
    Graph,
    assert_refs_resolve,
    seed_graph,
    t,
)

pytestmark = pytest.mark.asyncio

INTEL = f"/taxii2/api/collections/{INTEL_COLLECTION_ID}"


async def _token(
    session: AsyncSession, max_tlp: str = "clear", scopes: tuple[str, ...] = ("intel:read",)
) -> str:
    token = machine_auth.generate_token()
    await AsyncApiTokenRepo(session).create(
        name="intel",
        token_prefix=token[:8],
        token_hash=machine_auth.hash_token(token),
        scopes=list(scopes),
        max_tlp=max_tlp,
        created_by="tester",
        expires_at=None,
    )
    return token


async def _taxii(session: AsyncSession, **kw: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {await _token(session, **kw)}", "Accept": TAXII_MEDIA}


async def _pull(
    client: httpx.AsyncClient, h: dict[str, str], limit: int = 2, **params: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    q: dict[str, Any] = {"limit": limit, "added_after": AFTER, **params}
    while True:
        r = await client.get(INTEL + "/objects/", params=q, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        out += body.get("objects", [])
        if not body["more"]:
            assert "next" not in body
            return out
        q = {"limit": limit, "next": body["next"], **params}


def _labels(g: Graph, objs: list[dict[str, Any]]) -> list[str]:
    back = {v: k for k, v in g.ids.items()}
    return [back.get(o["id"], o["id"]) for o in objs]


@pytest.mark.parametrize(("max_tlp", "order"), [("clear", CLEAR_ORDER), ("red", RED_ORDER)])
@pytest.mark.parametrize("limit", [1, 2, 3, 100])
async def test_paging_mixed_kinds_no_gaps_no_dups(
    api_client: httpx.AsyncClient,
    api_session: AsyncSession,
    max_tlp: str,
    order: list[str],
    limit: int,
) -> None:
    g = await seed_graph(api_session)
    h = await _taxii(api_session, max_tlp=max_tlp)
    objs = await _pull(api_client, h, limit=limit)
    assert _labels(g, objs) == order
    assert_refs_resolve(objs)


async def test_amber_entity_hidden_from_clear_token(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    g = await seed_graph(api_session)
    clear = {o["id"]: o for o in await _pull(api_client, await _taxii(api_session), limit=50)}
    for hidden in ("H", "R2", "S2", "L", "S3"):
        assert g.ids[hidden] not in clear, hidden
    assert clear[g.ids["S1"]]["object_refs"] == sorted([g.ids["A"], g.ids["I"]])
    red = {
        o["id"]: o
        for o in await _pull(api_client, await _taxii(api_session, max_tlp="red"), limit=50)
    }
    assert red[g.ids["S1"]]["object_refs"] == sorted([g.ids["A"], g.ids["H"], g.ids["I"]])
    assert red[g.ids["S2"]]["object_refs"] == [g.ids["H"]]
    assert red[g.ids["S1"]]["external_references"] == [
        {"source_name": "article", "url": "https://news.example/1"}
    ]


async def test_merged_entity_revoked_and_its_relationship_kept(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    g = await seed_graph(api_session)
    objs = {o["id"]: o for o in await _pull(api_client, await _taxii(api_session), limit=50)}
    assert objs[g.ids["T"]]["revoked"] is True
    assert objs[g.ids["R4"]]["source_ref"] == g.ids["T"]
    assert objs[g.ids["R3"]]["source_ref"] == g.ids["I"]  # indikator memakai id STIX miliknya
    assert objs[g.ids["A"]]["aliases"] == ["Alpha Group"]


async def test_added_after_and_match_type(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    g = await seed_graph(api_session)
    h = await _taxii(api_session)
    r = await api_client.get(
        INTEL + "/objects/", params={"added_after": t(4).isoformat()}, headers=h
    )
    assert _labels(g, r.json()["objects"]) == ["R3", "R4", "S1"]
    assert r.headers["X-TAXII-Date-Added-First"] == "2020-01-01T00:05:00.000Z"
    assert r.headers["X-TAXII-Date-Added-Last"] == "2020-01-01T00:06:00.000Z"
    objs = await _pull(api_client, h, **{"match[type]": "intrusion-set"})
    assert _labels(g, objs) == ["A", "T"]
    objs = await _pull(api_client, h, **{"match[type]": "report,indicator"})
    assert _labels(g, objs) == ["I", "S1"]
    r = await api_client.get(
        INTEL + "/manifest/", params={"added_after": t(5).isoformat()}, headers=h
    )
    assert [m["id"] for m in r.json()["objects"]] == [g.ids["R4"], g.ids["S1"]]
    assert r.json()["objects"][0]["date_added"] == "2020-01-01T00:06:00.000Z"


async def test_object_by_id(api_client: httpx.AsyncClient, api_session: AsyncSession) -> None:
    g = await seed_graph(api_session)
    h = await _taxii(api_session)
    for label in ("A", "T", "R1", "I", "S1"):
        r = await api_client.get(f"{INTEL}/objects/{g.ids[label]}/", headers=h)
        assert r.status_code == 200, (label, r.text)
        assert [o["id"] for o in r.json()["objects"]] == [g.ids[label]]
    for label in ("H", "R2", "S2", "L", "S3"):
        r = await api_client.get(f"{INTEL}/objects/{g.ids[label]}/", headers=h)
        assert r.status_code == 404, label
    r = await api_client.get(f"{INTEL}/objects/{g.ids['S1']}/versions/", headers=h)
    assert r.json()["versions"] == ["2020-01-01T00:06:00.000Z"]
    r = await api_client.get(
        INTEL + "/objects/", params={"match[id]": f"{g.ids['A']},{g.ids['S1']}"}, headers=h
    )
    assert _labels(g, r.json()["objects"]) == ["A", "S1"]


async def test_scopes_per_collection(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    await seed_graph(api_session)
    ind_only = await _taxii(api_session, scopes=("indicators:read",))
    intel_only = await _taxii(api_session)
    both = await _taxii(api_session, scopes=("indicators:read", "intel:read"))

    r = await api_client.get("/taxii2/api/collections/", headers=ind_only)
    assert [c["id"] for c in r.json()["collections"]] == [COLLECTION_ID]
    r = await api_client.get("/taxii2/api/collections/", headers=intel_only)
    assert [c["id"] for c in r.json()["collections"]] == [INTEL_COLLECTION_ID]
    r = await api_client.get("/taxii2/api/collections/", headers=both)
    cols = r.json()["collections"]
    assert [c["id"] for c in cols] == [COLLECTION_ID, INTEL_COLLECTION_ID]
    assert cols[1]["title"] == "Vareon intel"

    assert (await api_client.get(INTEL + "/objects/", headers=ind_only)).status_code == 403
    assert (await api_client.get(INTEL + "/", headers=ind_only)).status_code == 403
    r = await api_client.get(
        f"/taxii2/api/collections/{COLLECTION_ID}/objects/", headers=intel_only
    )
    assert r.status_code == 403
    assert (await api_client.get("/taxii2/", headers=intel_only)).status_code == 200
    assert (await api_client.get(INTEL + "/objects/", headers=both)).status_code == 200


# ── REST /api/v2/entities, /api/v2/relationships ───────────────────────────


async def _rest(
    client: httpx.AsyncClient, path: str, token: str, **params: Any
) -> list[dict[str, Any]]:
    h = {"Authorization": f"Bearer {token}"}
    items: list[dict[str, Any]] = []
    q: dict[str, Any] = {"changed_after": AFTER, "limit": 1, **params}
    while True:
        r = await client.get(path, params=q, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        items += body["items"]
        if body["next_cursor"] is None:
            return items
        q = {**q, "cursor": body["next_cursor"]}


async def test_rest_entities(api_client: httpx.AsyncClient, api_session: AsyncSession) -> None:
    g = await seed_graph(api_session)
    token = await _token(api_session)
    items = await _rest(api_client, "/api/v2/entities", token)
    assert [i["stix_id"] for i in items] == [g.ids[x] for x in ("A", "M", "T", "L")]
    by = {i["stix_id"]: i for i in items}
    assert by[g.ids["A"]]["aliases"] == ["Alpha Group", "Alpha Panda"]
    assert by[g.ids["T"]]["merged_into_stix_id"] == g.ids["A"]
    assert by[g.ids["T"]]["revoked"] is True and by[g.ids["A"]]["revoked"] is False
    items = await _rest(api_client, "/api/v2/entities", token, type="malware")
    assert [i["stix_id"] for i in items] == [g.ids["M"]]
    red = await _rest(api_client, "/api/v2/entities", await _token(api_session, max_tlp="red"))
    assert g.ids["H"] in {i["stix_id"] for i in red}
    h = {"Authorization": f"Bearer {token}"}
    assert (await api_client.get("/api/v2/entities?type=bogus", headers=h)).status_code == 400
    assert (await api_client.get("/api/v2/entities?cursor=zz", headers=h)).status_code == 400


async def test_rest_relationships(api_client: httpx.AsyncClient, api_session: AsyncSession) -> None:
    g = await seed_graph(api_session)
    token = await _token(api_session)
    items = await _rest(api_client, "/api/v2/relationships", token)
    assert [i["stix_id"] for i in items] == [g.ids[x] for x in ("R1", "R3", "R4")]
    by = {i["stix_id"]: i for i in items}
    assert by[g.ids["R3"]]["source_ref"] == g.ids["I"]
    assert by[g.ids["R1"]]["target_ref"] == g.ids["M"]
    assert by[g.ids["R1"]]["confidence"] == 75
    red = await _rest(api_client, "/api/v2/relationships", await _token(api_session, max_tlp="red"))
    assert [i["stix_id"] for i in red] == [g.ids[x] for x in ("R1", "R2", "R3", "R4")]
    items = await _rest(api_client, "/api/v2/relationships", token, type="indicates")
    assert [i["stix_id"] for i in items] == [g.ids["R3"]]


async def test_rest_scope(api_client: httpx.AsyncClient, api_session: AsyncSession) -> None:
    ind = {"Authorization": f"Bearer {await _token(api_session, scopes=('indicators:read',))}"}
    intel = {"Authorization": f"Bearer {await _token(api_session)}"}
    assert (await api_client.get("/api/v2/entities", headers=ind)).status_code == 403
    assert (await api_client.get("/api/v2/relationships", headers=ind)).status_code == 403
    assert (await api_client.get("/api/v2/indicators", headers=intel)).status_code == 403
    assert (await api_client.get("/api/v2/entities", headers=intel)).status_code == 200


async def test_suppress_resends_relationships_and_report(
    api_client: httpx.AsyncClient, api_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 33: suppress membump relasi dan story yang menyentuh entitas, jadi tarikan inkremental
    membawa entitas revoked dan report tanpa entitas itu di `object_refs`."""
    g = await seed_graph(api_session)
    monkeypatch.setattr(feed, "FEED_SETTLE_SECONDS", -5)  # jam baru = clock_timestamp() > now()
    await api_session.execute(
        update(Entity).where(Entity.id == g.rows["A"]).values(suppressed=True)
    )
    await api_session.flush()
    h = await _taxii(api_session)
    objs = await _pull(api_client, h, limit=50, added_after=t(10).isoformat())
    labels = _labels(g, objs)
    assert labels[0] == "A" and labels[-1] == "S1"
    assert sorted(labels) == ["A", "R1", "R3", "S1"]
    by = {o["id"]: o for o in objs}
    assert by[g.ids["A"]]["revoked"] is True
    assert by[g.ids["S1"]]["object_refs"] == [g.ids["I"]]
    assert_refs_resolve([*by.values(), {"id": g.ids["M"]}, {"id": g.ids["I"]}])


async def test_hidden_relationships_and_vanishing_report(
    api_client: httpx.AsyncClient, api_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Relasi tersembunyi oleh TLP-nya sendiri (kedua ujung clear), oleh sumber indikator di atas
    TLP token, dan oleh sumber indikator tanpa pola STIX (`cve`); report yang satu-satunya ref
    terlihatnya disembunyikan ikut hilang."""
    g = await seed_graph(api_session)
    monkeypatch.setattr(feed, "FEED_SETTLE_SECONDS", -5)
    s = api_session
    a = await s.get(Entity, g.rows["A"])
    m = await s.get(Entity, g.rows["M"])
    assert a is not None and m is not None
    tool = await intel_support._entity(s, "tool", "Clear Tool")
    own_tlp = await intel_support._rel(s, a, "uses", tool)
    own_tlp.tlp = "amber"
    amber_ind = Indicator(
        type="domain", value="amber.example", stix_id=indicator_uuid("domain", "amber.example"),
        tlp="amber",
    )  # fmt: skip
    cve_ind = Indicator(
        type="cve", value="CVE-2020-0001", stix_id=indicator_uuid("cve", "CVE-2020-0001")
    )
    s.add_all([amber_ind, cve_ind])
    await s.flush()
    by_amber = await intel_support._rel(s, amber_ind, "indicates", m)
    by_cve = await intel_support._rel(s, cve_ind, "indicates", m)
    lone = await intel_support._entity(s, "malware", "Lone Worm")
    story, _ = await intel_support._story(s, 9, "Lone story", [lone])
    await s.flush()

    clear = await _taxii(s)
    red = await _taxii(s, max_tlp="red")
    report_id = f"report--{story.stix_id}"
    clear_ids = {o["id"] for o in await _pull(api_client, clear, limit=50)}
    red_ids = {o["id"] for o in await _pull(api_client, red, limit=50)}
    assert own_tlp.stix_id not in clear_ids and own_tlp.stix_id in red_ids
    assert by_amber.stix_id not in clear_ids and by_amber.stix_id in red_ids
    assert by_cve.stix_id not in clear_ids and by_cve.stix_id not in red_ids
    assert report_id in clear_ids

    await s.execute(update(Entity).where(Entity.id == lone.id).values(tlp="amber"))
    await s.flush()
    objs = await _pull(api_client, clear, limit=50)
    assert report_id not in {o["id"] for o in objs}
    assert lone.stix_id not in {o["id"] for o in objs}
    assert_refs_resolve(objs)
