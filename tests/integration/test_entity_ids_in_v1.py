"""P7c-2 Task 2: respons v1 yang dibangun dari mention entitas kini ikut membawa `entity_id`
(aditif; field lama tidak berubah). Id dicari SESUDAH agregasi, jadi hitungan tidak bergeser."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.models.entity import Entity
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.mitre import AsyncMitreHeatmapRepo
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_TODAY = datetime.date.today()


async def _entity_id(session: AsyncSession, type_: str, name: str) -> int:
    return (
        await session.execute(select(Entity.id).where(Entity.type == type_, Entity.name == name))
    ).scalar_one()


async def _seed(session: AsyncSession, n: int = 3, posted_on: datetime.date = _TODAY) -> list[int]:
    """`n` artikel: APT29 + WellMess + T1566 + Government + Indonesia (victim)."""
    await AsyncClientRepo(session).ensure_default()
    repo = AsyncArticleRepo(session)
    ids = []
    for i in range(n):
        a = await repo.upsert(
            url=f"https://example.com/apt29-{i}-{posted_on}",
            title=f"APT29 {i}",
            source="S",
            posted_on=posted_on,
        )
        await repo.set_enrichment(
            a,
            threat_actors=["APT29"],
            ttps=[("T1566", "Phishing")],
            malware=[("WellMess", "malware")],
            industries=["Government"],
            countries=[("ID", "victim")],
        )
        ids.append(a.id)
    await session.commit()
    return ids


async def test_article_out_entities(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    [aid] = await _seed(api_session, n=1)
    apt29 = await _entity_id(api_session, "intrusion-set", "APT29")
    resp = await api_client.get(f"/api/articles/{aid}", headers=auth_header())
    assert resp.status_code == 200
    body = resp.json()
    ents = body["entities"]
    assert {
        "id": apt29,
        "type": "intrusion-set",
        "name": "APT29",
        "external_id": None,
        "role": None,
    } in ents
    [indonesia] = [e for e in ents if e["type"] == "location"]
    assert indonesia["role"] == "victim"
    assert indonesia["external_id"] == "ID"
    assert {e["type"] for e in ents} >= {"intrusion-set", "malware", "attack-pattern", "identity"}
    # field lama tidak berubah
    assert body["threat_actors"] == ["APT29"]
    assert body["victim_countries"] == ["ID"]
    assert [t["id"] for t in body["ttps"]] == ["T1566"]
    assert body["malware"] == [{"name": "WellMess", "kind": "malware"}]
    assert body["impacted_industries"] == ["Government"]


async def test_trending_entity_id(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed(api_session, n=3)
    apt29 = await _entity_id(api_session, "intrusion-set", "APT29")
    t1566 = await _entity_id(api_session, "attack-pattern", "Phishing")
    resp = await api_client.get("/api/dashboard/trending", headers=auth_header())
    assert resp.status_code == 200
    items = resp.json()["items"]
    [actor] = [i for i in items if i["kind"] == "actor"]
    [ttp] = [i for i in items if i["kind"] == "ttp"]
    assert (actor["name"], actor["entity_id"], actor["count"]) == ("APT29", apt29, 3)
    assert (ttp["ttp_id"], ttp["entity_id"], ttp["count"]) == ("T1566", t1566, 3)


async def test_spikes_entity_id(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    for i in range(10):
        await _seed(api_session, n=1, posted_on=_TODAY - datetime.timedelta(days=20 - i))
    await _seed(api_session, n=8, posted_on=_TODAY)
    apt29 = await _entity_id(api_session, "intrusion-set", "APT29")
    resp = await api_client.get("/api/spikes", params={"z_threshold": 1.5}, headers=auth_header())
    assert resp.status_code == 200
    body = resp.json()
    [spike] = [s for s in body["threat_actors"] if s["entity"] == "APT29"]
    assert (spike["entity_id"], spike["count"]) == (apt29, 8)
    gov = await _entity_id(api_session, "identity", "Government")
    assert {s["entity"]: s["entity_id"] for s in body["industries"]}["Government"] == gov
    countries = {s["entity"]: s["entity_id"] for s in body["countries"]}
    assert countries["ID"] == await _entity_id(api_session, "location", "Indonesia")


async def test_mitre_row_ids_and_ttp_ids(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed(api_session, n=2)
    apt29 = await _entity_id(api_session, "intrusion-set", "APT29")
    t1566 = await _entity_id(api_session, "attack-pattern", "Phishing")
    resp = await api_client.get("/api/mitre/heatmap", headers=auth_header())
    body = resp.json()
    assert body["rows"] == ["APT29"]
    assert body["row_ids"] == [apt29]
    assert body["matrix"] == [[2]]
    assert [(t["id"], t["entity_id"]) for t in body["ttps"]] == [("T1566", t1566)]

    direct = await AsyncMitreHeatmapRepo(api_session).get_heatmap(view="ta", days=90)
    assert direct["matrix"] == [[2]]
