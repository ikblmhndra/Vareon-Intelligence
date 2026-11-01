"""Graf kecil untuk test feed `intel` (P7c Task 15): entitas, relasi, indikator, story.

Semua baris yang sudah ada (seed sektor/negara dari migrasi) dimundurkan ke 2000-01-01 di dalam
transaksi test, lalu graf diberi jam feed tetap di 2020-01-01 + n menit. Tarikan dengan
`added_after=2001-01-01` jadi hanya berisi graf ini; settle lag bawaan tidak perlu dimatikan.

Urutan feed yang diharapkan (token clear), kunci `(waktu, jenis, id)`:
A(t1) M(t1) T(t3) R1(t4) I(t4) R3(t5) R4(t6) S1(t6). H, R2, S2 hanya untuk token amber ke atas;
L (lokasi tanpa negara) dan S3 (hanya mention tombstone) tidak pernah terbit."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from cti_core.db.models.article import Article
from cti_core.db.models.entity import Entity, EntityAlias, EntityMention, Relationship
from cti_core.db.models.indicator import Indicator, IndicatorSource
from cti_core.db.models.story import Story
from cti_core.entity import alias_norm, entity_stix_id, relationship_stix_id
from cti_core.indicator.stix_id import indicator_uuid
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

BASE = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
AFTER = "2001-01-01T00:00:00Z"


def t(minutes: int) -> datetime.datetime:
    return BASE + datetime.timedelta(minutes=minutes)


@dataclass
class Graph:
    ids: dict[str, str]  # label -> STIX id
    rows: dict[str, int]  # label -> id baris


async def _entity(s: AsyncSession, type_: str, name: str, *aliases: str, **kw: object) -> Entity:
    e = Entity(type=type_, stix_id=entity_stix_id(type_, name), name=name, source="analyst", **kw)  # type: ignore[arg-type]
    s.add(e)
    await s.flush()
    for a in [name, *aliases]:
        s.add(
            EntityAlias(
                entity_id=e.id,
                entity_type=type_,
                alias=a,
                alias_norm=alias_norm(a),
                source="analyst",
            )
        )
    await s.flush()
    return e


async def _rel(s: AsyncSession, src: Entity | Indicator, rtype: str, dst: Entity) -> Relationship:
    if isinstance(src, Indicator):
        src_stix = f"indicator--{src.stix_id}"
        kw = {"source_indicator_id": src.id}
    else:
        src_stix = src.stix_id
        kw = {"source_entity_id": src.id}
    r = Relationship(
        stix_id=relationship_stix_id(src_stix, rtype, dst.stix_id),
        relationship_type=rtype,
        target_entity_id=dst.id,
        provenance="analyst",
        confidence=75,
        **kw,
    )
    s.add(r)
    await s.flush()
    return r


async def _story(
    s: AsyncSession, n: int, title: str, mentions: list[Entity]
) -> tuple[Story, Article]:
    st = Story(title=title, lead_source="src")
    s.add(st)
    await s.flush()
    art = Article(
        url=f"https://news.example/{n}", url_hash=f"intel-{n}", title=title, source="src",
        story_id=st.id,
    )  # fmt: skip
    s.add(art)
    await s.flush()
    for e in mentions:
        s.add(
            EntityMention(article_id=art.id, entity_id=e.id, method="analyst", matched_alias=e.name)
        )
    await s.flush()
    return st, art


async def age_existing(s: AsyncSession) -> None:
    for table in ("entities", "relationships", "indicators", "stories"):
        await s.execute(text(f"UPDATE {table} SET feed_changed_at = '2000-01-01T00:00:00Z'"))


async def seed_graph(s: AsyncSession) -> Graph:
    await age_existing(s)
    a = await _entity(s, "intrusion-set", "Alpha Panda", "Alpha Group")
    m = await _entity(s, "malware", "Gremlin")
    h = await _entity(s, "intrusion-set", "Hidden Bear", tlp="amber")
    tomb = await _entity(s, "intrusion-set", "Old Alpha", merged_into_id=a.id)
    loc = await _entity(s, "location", "Nowhere")
    ind = Indicator(
        type="domain",
        value="evil.example.com",
        stix_id=indicator_uuid("domain", "evil.example.com"),
    )
    s.add(ind)
    await s.flush()
    r1 = await _rel(s, a, "uses", m)
    r2 = await _rel(s, h, "uses", m)
    r3 = await _rel(s, ind, "indicates", a)
    r4 = await _rel(s, tomb, "uses", m)
    s1, a1 = await _story(s, 1, "Alpha campaign", [a, h])
    s.add(IndicatorSource(indicator_id=ind.id, article_id=a1.id, url=a1.url, source_name="src"))
    s2, _ = await _story(s, 2, "Bear story", [h])
    s3, _ = await _story(s, 3, "Old story", [tomb])
    await s.flush()

    clocks = [
        (Entity, a.id, 1), (Entity, m.id, 1), (Entity, h.id, 2), (Entity, tomb.id, 3),
        (Entity, loc.id, 3), (Indicator, ind.id, 4), (Relationship, r1.id, 4),
        (Relationship, r2.id, 5), (Relationship, r3.id, 5), (Relationship, r4.id, 6),
        (Story, s1.id, 6), (Story, s2.id, 7), (Story, s3.id, 7),
    ]  # fmt: skip
    for model, row_id, minute in clocks:
        await s.execute(
            update(model).where(model.id == row_id).values(feed_changed_at=t(minute))  # type: ignore[attr-defined]
        )
    await s.flush()
    for obj in (a, m, h, tomb, loc, ind, r1, r2, r3, r4, s1, s2, s3):
        await s.refresh(obj)

    ids = {
        "A": a.stix_id, "M": m.stix_id, "H": h.stix_id, "T": tomb.stix_id, "L": loc.stix_id,
        "I": f"indicator--{ind.stix_id}", "R1": r1.stix_id, "R2": r2.stix_id, "R3": r3.stix_id,
        "R4": r4.stix_id, "S1": f"report--{s1.stix_id}", "S2": f"report--{s2.stix_id}",
        "S3": f"report--{s3.stix_id}",
    }  # fmt: skip
    rows = {
        "A": a.id, "M": m.id, "H": h.id, "T": tomb.id, "L": loc.id, "I": ind.id, "R1": r1.id,
        "R2": r2.id, "R3": r3.id, "R4": r4.id, "S1": s1.id, "S2": s2.id, "S3": s3.id,
    }  # fmt: skip
    return Graph(ids=ids, rows=rows)


CLEAR_ORDER = ["A", "M", "T", "R1", "I", "R3", "R4", "S1"]
RED_ORDER = ["A", "M", "H", "T", "R1", "I", "R2", "R3", "R4", "S1", "S2"]


def assert_refs_resolve(objects: list[dict[str, object]]) -> None:
    """Integritas ref: tiap `source_ref`/`target_ref`/`object_refs` menunjuk objek di tarikan yang
    sama. `object_marking_refs` menunjuk marking TLP 2.0 resmi OASIS (id tetap), di luar koleksi."""
    have = {o["id"] for o in objects}
    for o in objects:
        refs = [o.get("source_ref"), o.get("target_ref"), *(o.get("object_refs") or [])]  # type: ignore[misc]
        missing = [r for r in refs if r is not None and r not in have]
        assert not missing, (o["id"], missing)
