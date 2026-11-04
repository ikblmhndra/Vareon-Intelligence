"""Hunting pack (P7e Task 6) lewat HTTP ke Postgres NYATA: tier teknik story (primary/inferred/llm),
hanya indikator aktif, filter TLP per token di `/api/v2`, scope `hunt:read`, pack entitas (relasi
`uses`/`indicates`, jendela `days`, batas 2.000), entitas merged/tipe tak didukung -> 404, zip."""

from __future__ import annotations

import datetime
import io
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from cti_api import machine_auth
from cti_core.db.models.article import Article
from cti_core.db.models.attack import AttackGroup, AttackRelationship, AttackTechnique
from cti_core.db.models.entity import Entity, EntityMention, Relationship
from cti_core.db.models.hunt import SigmaRule
from cti_core.db.models.indicator import Indicator, IndicatorSource
from cti_core.db.models.story import Story
from cti_core.db.repositories.auth import AsyncApiTokenRepo
from httpx import AsyncClient
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

Header = Callable[..., dict[str, str]]
NOW = datetime.datetime.now(datetime.UTC)


@pytest.fixture(autouse=True)
async def _own_sigma_rules(api_session: AsyncSession) -> None:
    # test lifespan lain meng-commit snapshot bawaan (3.302 rule); pakai rule sendiri saja
    await api_session.execute(delete(SigmaRule))


async def _token(
    s: AsyncSession, scopes: tuple[str, ...] = ("hunt:read",), max_tlp: str = "red"
) -> dict[str, str]:
    token = machine_auth.generate_token()
    await AsyncApiTokenRepo(s).create(
        name="hunt",
        token_prefix=token[:8],
        token_hash=machine_auth.hash_token(token),
        scopes=list(scopes),
        max_tlp=max_tlp,
        created_by="tester",
        expires_at=None,
    )
    return {"Authorization": f"Bearer {token}"}


async def _entity(s: AsyncSession, type_: str, name: str, **kw: object) -> Entity:
    e = Entity(type=type_, stix_id=f"{type_}--hunt-{name}", name=name, source="analyst", **kw)
    s.add(e)
    await s.flush()
    return e


_n = 0


async def _article(
    s: AsyncSession, story: Story | None = None, posted: datetime.date | None = None
) -> Article:
    global _n
    _n += 1
    a = Article(
        url=f"http://hunt/{_n}",
        url_hash=f"hunt-{_n}",
        title=f"hunt article {_n}",
        source="src",
        posted_on=posted,
        story_id=None if story is None else story.id,
    )
    s.add(a)
    await s.flush()
    return a


async def _story(s: AsyncSession, title: str, last_seen: datetime.datetime = NOW) -> Story:
    st = Story(title=title, lead_source="src", last_seen_at=last_seen)
    s.add(st)
    await s.flush()
    return st


async def _mention(s: AsyncSession, e: Entity, a: Article, method: str = "explicit") -> None:
    s.add(EntityMention(article_id=a.id, entity_id=e.id, method=method, matched_alias=e.name))
    await s.flush()


async def _indicator(
    s: AsyncSession, type_: str, value: str, article: Article | None = None, **kw: object
) -> Indicator:
    ind = Indicator(type=type_, value=value, **kw)  # type: ignore[arg-type]
    s.add(ind)
    await s.flush()
    if article is not None:
        s.add(
            IndicatorSource(
                indicator_id=ind.id, article_id=article.id, url=article.url, source_name="src"
            )
        )
        await s.flush()
    return ind


async def _sigma(s: AsyncSession, title: str, *techniques: str) -> None:
    s.add(
        SigmaRule(
            id=uuid.uuid4(),
            title=title,
            author="Tester",
            level="high",
            status="test",
            ruleset="core",
            logsource={"category": "process_creation", "product": "windows"},
            techniques=list(techniques),
            path=f"rules/windows/{title}.yml",
            release="r2026-01-01",
            yaml=f"title: {title}\n",
        )
    )
    await s.flush()


@dataclass
class Seeded:
    id: int
    article: Article


@pytest.fixture
async def seeded_story(api_session: AsyncSession) -> Seeded:
    """Story: T1059 explicit, T1190 llm, aktor yang di ATT&CK `uses` T1566 (inferred); ip aktif,
    domain dicabut, url kedaluwarsa; rule Sigma untuk T1059 dan T1190."""
    s = api_session
    st = await _story(s, "Hunt story")
    a = await _article(s, st)
    await _mention(s, await _entity(s, "attack-pattern", "Cmd", external_id="T1059"), a)
    await _mention(s, await _entity(s, "attack-pattern", "Exploit", external_id="T1190"), a, "llm")
    await _mention(s, await _entity(s, "intrusion-set", "HuntGroup7"), a, "dictionary")
    s.add_all(
        [
            AttackGroup(stix_id="intrusion-set--hunt7", group_id="G9907", name="HuntGroup7"),
            AttackTechnique(stix_id="attack-pattern--h1566", attack_id="T1566", name="Phishing"),
        ]
    )
    await s.flush()
    s.add(
        AttackRelationship(
            stix_id="relationship--hunt1",
            relationship_type="uses",
            source_ref="intrusion-set--hunt7",
            source_type="intrusion-set",
            target_ref="attack-pattern--h1566",
            target_type="attack-pattern",
            domain="enterprise",
        )
    )
    past = NOW - datetime.timedelta(days=1)
    await _indicator(s, "ip", "198.51.100.7", a)
    await _indicator(s, "domain", "revoked.example", a, revoked_at=past)
    await _indicator(s, "url", "http://expired.example/x", a, valid_until=past)
    await _sigma(s, "cmd-rule", "T1059")
    await _sigma(s, "exploit-rule", "T1190")
    await s.commit()
    return Seeded(st.id, a)


async def test_story_pack_tiers_and_active_only(
    api_client: AsyncClient, auth_header: Header, seeded_story: Seeded
) -> None:
    r = await api_client.get(f"/api/hunt-packs/story/{seeded_story.id}", headers=auth_header())
    assert r.status_code == 200, r.text
    body = r.json()
    assert {t["attack_id"]: t["tier"] for t in body["techniques"]} == {
        "T1059": "primary",
        "T1566": "inferred",
        "T1190": "llm",
    }
    assert [i["value"] for i in body["iocs"]["network_traffic"]] == ["198.51.100.7"]
    assert set(body["iocs"]) == {"network_traffic"}
    assert [m["via_technique"] for m in body["sigma"]] == ["T1059"]
    assert body["anchor"] == {
        "type": "story",
        "id": seeded_story.id,
        "title": "Hunt story",
        "entity_type": None,
    }
    assert body["truncated"] is False
    assert "yaml" not in r.text


async def test_story_pack_include_llm_adds_sigma(
    api_client: AsyncClient, auth_header: Header, seeded_story: Seeded
) -> None:
    r = await api_client.get(
        f"/api/hunt-packs/story/{seeded_story.id}?include=llm", headers=auth_header()
    )
    assert any(m["via_technique"] == "T1190" for m in r.json()["sigma"])
    assert r.json()["include"] == ["llm"]


async def test_story_pack_without_techniques(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    st = await _story(api_session, "Plain story")
    await _indicator(api_session, "ip", "198.51.100.8", await _article(api_session, st))
    await _sigma(api_session, "cmd-rule", "T1059")
    await api_session.commit()
    r = await api_client.get(f"/api/hunt-packs/story/{st.id}", headers=auth_header())
    assert r.status_code == 200 and r.json()["sigma"] == []
    assert r.json()["techniques"] == []
    assert r.json()["counts"]["indicators"] == 1


async def test_unknown_story_404(api_client: AsyncClient, auth_header: Header) -> None:
    r = await api_client.get("/api/hunt-packs/story/987654321", headers=auth_header())
    assert r.status_code == 404


async def test_v2_tlp_filter(
    api_client: AsyncClient, api_session: AsyncSession, seeded_story: Seeded
) -> None:
    await _indicator(api_session, "ip", "203.0.113.9", seeded_story.article, tlp="amber")
    h = await _token(api_session, max_tlp="clear")
    await api_session.commit()
    r = await api_client.get(f"/api/v2/hunt-packs/story/{seeded_story.id}", headers=h)
    assert r.status_code == 200 and "203.0.113.9" not in r.text
    assert "198.51.100.7" in r.text


async def test_v2_scope_required(
    api_client: AsyncClient, api_session: AsyncSession, seeded_story: Seeded
) -> None:
    h = await _token(api_session, scopes=("indicators:read",))
    await api_session.commit()
    r = await api_client.get(f"/api/v2/hunt-packs/story/{seeded_story.id}", headers=h)
    assert r.status_code == 403


async def test_entity_pack_relationships_and_window(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    actor = await _entity(s, "intrusion-set", "HuntWindowGroup")
    tech = await _entity(s, "attack-pattern", "Cmd", external_id="T1059")
    revoked_tech = await _entity(s, "attack-pattern", "Gone", external_id="T1001")
    s.add_all(
        [
            Relationship(
                stix_id="relationship--hw1",
                relationship_type="uses",
                source_entity_id=actor.id,
                target_entity_id=tech.id,
                provenance="attack",
            ),
            Relationship(
                stix_id="relationship--hw2",
                relationship_type="uses",
                source_entity_id=actor.id,
                target_entity_id=revoked_tech.id,
                provenance="attack",
                revoked_at=NOW,
            ),
        ]
    )
    recent = await _article(s, await _story(s, "recent", NOW - datetime.timedelta(days=30)))
    old = await _article(s, await _story(s, "old", NOW - datetime.timedelta(days=200)))
    loose = await _article(s, posted=(NOW - datetime.timedelta(days=10)).date())
    for a in (recent, old, loose):
        await _mention(s, actor, a, "dictionary")
    await _indicator(s, "ip", "198.51.100.30", recent)
    await _indicator(s, "ip", "198.51.100.200", old)
    await _indicator(s, "ip", "198.51.100.10", loose)
    linked = await _indicator(s, "domain", "linked.example")
    s.add(
        Relationship(
            stix_id="relationship--hw3",
            relationship_type="indicates",
            source_indicator_id=linked.id,
            target_entity_id=actor.id,
            provenance="analyst",
        )
    )
    await _sigma(s, "cmd-rule", "T1059.001")
    await s.commit()

    r = await api_client.get(f"/api/hunt-packs/entity/{actor.id}", headers=auth_header())
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(t["attack_id"], t["tier"]) for t in body["techniques"]] == [("T1059", "primary")]
    assert {i["value"] for v in body["iocs"].values() for i in v} == {
        "198.51.100.30",
        "198.51.100.10",
        "linked.example",
    }
    assert [(m["match"], m["via_technique"]) for m in body["sigma"]] == [("sub", "T1059")]
    assert body["anchor"]["entity_type"] == "intrusion-set"

    r = await api_client.get(f"/api/hunt-packs/entity/{actor.id}?days=365", headers=auth_header())
    assert "198.51.100.200" in r.text


async def test_attack_pattern_entity_is_sigma_only(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    tech = await _entity(api_session, "attack-pattern", "Cmd", external_id="T1059")
    await _sigma(api_session, "cmd-rule", "T1059")
    await api_session.commit()
    body = (await api_client.get(f"/api/hunt-packs/entity/{tech.id}", headers=auth_header())).json()
    assert [t["attack_id"] for t in body["techniques"]] == ["T1059"]
    assert len(body["sigma"]) == 1 and body["iocs"] == {}


async def test_entity_pack_truncated(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    actor = await _entity(s, "malware", "HuntManyLoader")
    ids = (
        await s.scalars(
            insert(Indicator)
            .values([{"type": "ip", "value": f"10.9.{n // 250}.{n % 250}"} for n in range(2001)])
            .returning(Indicator.id)
        )
    ).all()
    await s.execute(
        insert(Relationship).values(
            [
                {
                    "stix_id": f"relationship--many-{i}",
                    "relationship_type": "indicates",
                    "source_indicator_id": i,
                    "target_entity_id": actor.id,
                    "provenance": "analyst",
                }
                for i in ids
            ]
        )
    )
    await s.commit()
    body = (
        await api_client.get(f"/api/hunt-packs/entity/{actor.id}", headers=auth_header())
    ).json()
    assert body["counts"]["indicators"] == 2000
    assert body["truncated"] is True


async def test_merged_entity_404(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    target = await _entity(api_session, "intrusion-set", "HuntTarget")
    gone = await _entity(api_session, "intrusion-set", "HuntGone", merged_into_id=target.id)
    h = await _token(api_session)
    await api_session.commit()
    r = await api_client.get(f"/api/v2/hunt-packs/entity/{gone.id}", headers=h)
    assert r.status_code == 404
    assert r.json()["error"]["details"]["merged_into_id"] == target.id
    r = await api_client.get(f"/api/hunt-packs/entity/{gone.id}", headers=auth_header())
    assert r.status_code == 404
    assert r.json()["detail"]["merged_into_id"] == target.id


async def test_unsupported_entity_type_404(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    loc = await _entity(api_session, "location", "HuntLand")
    await api_session.commit()
    r = await api_client.get(f"/api/hunt-packs/entity/{loc.id}", headers=auth_header())
    assert r.status_code == 404


async def test_zip_format(
    api_client: AsyncClient, api_session: AsyncSession, seeded_story: Seeded
) -> None:
    h = await _token(api_session)
    await api_session.commit()
    r = await api_client.get(f"/api/v2/hunt-packs/story/{seeded_story.id}?format=zip", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert (
        r.headers["content-disposition"]
        == f'attachment; filename="hunt-story-{seeded_story.id}.zip"'
    )
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "sigma/" in "".join(names)
    assert "LICENSE.Detection.Rules.md" in names


async def test_suppressed_entity_anchor_404(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    ent = await _entity(api_session, "intrusion-set", "HuntSuppressed", suppressed=True)
    h = await _token(api_session)
    await api_session.commit()
    r = await api_client.get(f"/api/hunt-packs/entity/{ent.id}", headers=auth_header())
    assert r.status_code == 404
    assert (
        await api_client.get(f"/api/v2/hunt-packs/entity/{ent.id}", headers=h)
    ).status_code == 404


async def test_entity_uses_excludes_suppressed_technique(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    actor = await _entity(s, "malware", "HuntSuppUses")
    live = await _entity(s, "attack-pattern", "Live", external_id="T1059")
    hidden = await _entity(s, "attack-pattern", "Hidden", external_id="T1001", suppressed=True)
    for i, t in enumerate((live, hidden)):
        s.add(
            Relationship(
                stix_id=f"relationship--hsu{i}",
                relationship_type="uses",
                source_entity_id=actor.id,
                target_entity_id=t.id,
                provenance="attack",
            )
        )
    await s.commit()
    body = (
        await api_client.get(f"/api/hunt-packs/entity/{actor.id}", headers=auth_header())
    ).json()
    assert [t["attack_id"] for t in body["techniques"]] == ["T1059"]


async def test_story_legacy_mention_is_llm_tier(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Header
) -> None:
    s = api_session
    st = await _story(s, "Legacy story")
    a = await _article(s, st)
    await _mention(s, await _entity(s, "attack-pattern", "Old", external_id="T1027"), a, "legacy")
    await _mention(s, await _entity(s, "attack-pattern", "Kw", external_id="T1059"), a, "keyword")
    await s.commit()
    body = (await api_client.get(f"/api/hunt-packs/story/{st.id}", headers=auth_header())).json()
    assert {t["attack_id"]: t["tier"] for t in body["techniques"]} == {
        "T1059": "primary",
        "T1027": "llm",
    }
