"""`GET /api/articles/{id}/inferred-ttps` (P4): teknik yang DIKAITKAN ATT&CK ke aktor/malware
artikel, tanpa disimpan -- ditandai terpisah dari TTP yang disebut artikel."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.models.attack import (
    AttackGroup,
    AttackRelationship,
    AttackSoftware,
    AttackTechnique,
)
from cti_core.db.models.entity import Entity
from cti_core.db.repositories.article import AsyncArticleRepo, MentionInput
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


def _tech(stix: str, attack_id: str, name: str) -> AttackTechnique:
    return AttackTechnique(stix_id=stix, attack_id=attack_id, name=name)


def _uses(n: int, source: str, target: str) -> AttackRelationship:
    return AttackRelationship(
        stix_id=f"relationship--{n}",
        relationship_type="uses",
        source_ref=source,
        source_type="intrusion-set",
        target_ref=target,
        target_type="attack-pattern",
        domain="enterprise",
    )


async def _seed_attack(session: AsyncSession) -> None:
    session.add_all(
        [
            AttackGroup(
                stix_id="intrusion-set--apt29",
                group_id="G0016",
                name="APT29",
                aliases=["Cozy Bear", "The Dukes"],
            ),
            AttackSoftware(
                stix_id="tool--mimikatz",
                software_id="S0002",
                name="Mimikatz",
                software_type="tool",
                aliases=[],
            ),
            _tech("attack-pattern--t1566", "T1566", "Phishing"),
            _tech("attack-pattern--t1003", "T1003", "OS Credential Dumping"),
            _tech("attack-pattern--t1059", "T1059", "Command and Scripting Interpreter"),
        ]
    )
    await session.flush()
    session.add_all(
        [
            _uses(1, "intrusion-set--apt29", "attack-pattern--t1566"),
            # duplikat teknik yang sama via relasi lain: harus dedup
            _uses(2, "intrusion-set--apt29", "attack-pattern--t1566"),
            _uses(3, "intrusion-set--apt29", "attack-pattern--t1059"),
            _uses(4, "tool--mimikatz", "attack-pattern--t1003"),
        ]
    )
    await session.flush()


async def _article(
    session: AsyncSession,
    *,
    actors: tuple[str, ...] = (),
    malware: tuple[tuple[str, str], ...] = (),
) -> int:
    await AsyncClientRepo(session).ensure_default()
    repo = AsyncArticleRepo(session)
    art = await repo.upsert(
        url="https://x.example/a",
        title="T",
        source="S",
        posted_on=datetime.date.today(),
    )
    aid = art.id
    await repo.add_mentions(
        art,
        [MentionInput("intrusion-set", a, "llm", a) for a in actors]
        + [MentionInput(k, n, "dictionary", n) for n, k in malware],
    )
    await session.commit()
    session.expire_all()
    return aid


async def test_inferred_ttps_for_attack_actor(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_attack(api_session)
    aid = await _article(api_session, actors=("Apt29",))
    resp = await api_client.get(f"/api/articles/{aid}/inferred-ttps", headers=auth_header())
    assert resp.status_code == 200
    [got] = resp.json()
    # `entity_id` aditif: aktor ada entitasnya (dari mention), teknik ATT&CK seed ini tidak.
    assert isinstance(got.pop("entity_id"), int)
    assert got == {
        "entity": "Apt29",
        "kind": "actor",
        "attack_id": "G0016",
        "techniques": [
            {"id": "T1059", "name": "Command and Scripting Interpreter", "entity_id": None},
            {"id": "T1566", "name": "Phishing", "entity_id": None},
        ],
    }


async def test_inferred_ttps_alias_and_malware(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_attack(api_session)
    aid = await _article(api_session, actors=("Cozy bear",), malware=(("mimikatz", "tool"),))
    resp = await api_client.get(f"/api/articles/{aid}/inferred-ttps", headers=auth_header())
    body = resp.json()
    by_kind = {e["kind"]: e for e in body}
    assert by_kind["actor"]["attack_id"] == "G0016"
    assert by_kind["tool"]["attack_id"] == "S0002"
    assert by_kind["tool"]["techniques"] == [
        {"id": "T1003", "name": "OS Credential Dumping", "entity_id": None}
    ]


async def test_inferred_ttps_unknown_entity_omitted(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_attack(api_session)
    aid = await _article(api_session, actors=("Nobody group",), malware=(("Zzzware", "malware"),))
    resp = await api_client.get(f"/api/articles/{aid}/inferred-ttps", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == []


async def test_inferred_ttps_404(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/articles/999999/inferred-ttps", headers=auth_header())
    assert resp.status_code == 404


async def test_inferred_entity_and_technique_ids(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    from sqlalchemy import select

    await _seed_attack(api_session)
    # Entitas teknik T1566 ada di katalog entitas; T1059 sengaja tidak (id harus `None`).
    api_session.add(
        Entity(
            type="attack-pattern",
            stix_id="attack-pattern--t1566",
            name="Phishing",
            source="attack",
            external_id="T1566",
        )
    )
    await api_session.flush()
    aid = await _article(api_session, actors=("Apt29",), malware=(("mimikatz", "tool"),))
    resp = await api_client.get(f"/api/articles/{aid}/inferred-ttps", headers=auth_header())
    by_kind = {e["kind"]: e for e in resp.json()}

    async def ent(type_: str, **kw: str) -> int:
        stmt = select(Entity.id).where(Entity.type == type_, Entity.merged_into_id.is_(None))
        for k, v in kw.items():
            stmt = stmt.where(getattr(Entity, k) == v)
        return (await api_session.execute(stmt)).scalars().first()  # type: ignore[return-value]

    assert by_kind["actor"]["entity_id"] == await ent("intrusion-set", name="Apt29")
    assert by_kind["tool"]["entity_id"] == await ent("tool", name="mimikatz")
    t1566 = await ent("attack-pattern", external_id="T1566")
    techs = {t["id"]: t["entity_id"] for t in by_kind["actor"]["techniques"]}
    assert techs["T1566"] == t1566
    assert isinstance(t1566, int)
    assert techs["T1059"] is None
