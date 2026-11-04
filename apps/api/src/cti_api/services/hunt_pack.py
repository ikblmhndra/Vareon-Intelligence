"""Collector hunting pack (P7e spec 5.1/5.2): baca story/entitas dari DB, lalu serahkan nilai
polos ke builder murni `hunt_builder`. Dipakai route web (JWT, tanpa filter TLP: R1) dan mesin
(`/api/v2`, filter TLP token).

Semua query berbasis himpunan (tanpa query per indikator); satu-satunya kerja per artikel adalah
`inferred_ttps.for_article` (artikel story dimuat sekali beserta mention-nya lewat `selectin`).
Indikator selalu hanya yang `state == 'active'`; jumlah yang disembunyikan TLP tidak dilaporkan.
Tanggal artikel tanpa story = `posted_on`, jatuh ke `created_at` (Ruling 11, sama dengan
`services.entities`), karena `articles` tidak punya kolom `published_at`.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from cti_core.db.models.article import Article
from cti_core.db.models.entity import Entity, EntityMention, ReferenceSnapshot, Relationship
from cti_core.db.models.hunt import SigmaRule
from cti_core.db.models.indicator import Indicator, IndicatorSource
from cti_core.db.models.story import Story
from cti_core.hunt.sigma import SIGMA_SNAPSHOT, SNAPSHOT_DIR
from cti_core.indicator.marking import tlp_allowed
from sqlalchemy import Date, Select, String, and_, cast, column, exists, func, or_, select, union
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from cti_api.services import inferred_ttps
from cti_api.services.hunt_builder import (
    AnchorIn,
    HuntPack,
    IndicatorIn,
    SigmaIn,
    TechniqueIn,
    build_pack,
    merge_tiers,
    pack_zip,
)

ENTITY_ANCHOR_TYPES = ("intrusion-set", "malware", "tool", "campaign", "attack-pattern")
PRIMARY_METHODS = frozenset({"explicit", "keyword", "analyst"})
ENTITY_INDICATOR_CAP = 2000
LICENSE_FILE = SNAPSHOT_DIR / "LICENSE.Detection.Rules.md"


class AnchorNotFound(Exception):
    """Story/entitas tidak ada, atau tipe entitas tidak punya pack -> 404."""


class AnchorMerged(Exception):
    """Entitas tombstone -> 404 + `merged_into_id` (web mengalihkan, seperti halaman entitas)."""

    def __init__(self, into_id: int) -> None:
        super().__init__(f"merged into {into_id}")
        self.into_id = into_id


@dataclass(frozen=True)
class Collected:
    anchor: AnchorIn
    techniques: list[TechniqueIn]
    indicators: list[IndicatorIn]
    truncated: bool


def _indicator_select(max_tlp: str | None) -> Select[Any]:
    """Filter indikator di satu tempat (spec 5.2): aktif, dan TLP token bila ada."""
    stmt = select(Indicator.type, Indicator.value, Indicator.valid_until, Indicator.tlp).where(
        Indicator.state == "active"
    )
    if max_tlp is not None:
        stmt = stmt.where(Indicator.tlp.in_(tlp_allowed(max_tlp)))
    return stmt


def _to_in(rows: Any) -> list[IndicatorIn]:
    return [IndicatorIn(r.type, r.value, r.valid_until, r.tlp) for r in rows]


async def collect_story(session: AsyncSession, story_id: int, *, max_tlp: str | None) -> Collected:
    story = await session.get(Story, story_id)
    if story is None:
        raise AnchorNotFound(f"story {story_id}")
    articles = (await session.scalars(select(Article).where(Article.story_id == story_id))).all()
    techniques: list[TechniqueIn] = []
    for a in articles:
        for m in a.mentions_of("attack-pattern"):
            if m.entity.external_id:
                # primary = persis explicit/keyword/analyst; `legacy` dan metode lain tak terjamin
                tier: Literal["primary", "llm"] = (
                    "primary" if m.method in PRIMARY_METHODS else "llm"
                )
                techniques.append(TechniqueIn(m.entity.external_id, m.entity.name, tier))
        for inferred in await inferred_ttps.for_article(session, a):
            techniques += [TechniqueIn(t.id, t.name, "inferred") for t in inferred.techniques]
    member_sources = (
        select(IndicatorSource.indicator_id)
        .join(Article, Article.id == IndicatorSource.article_id)
        .where(Article.story_id == story_id)
    )
    rows = await session.execute(
        _indicator_select(max_tlp)
        .where(Indicator.id.in_(member_sources))
        .order_by(Indicator.last_seen_at.desc(), Indicator.id.desc())
    )
    return Collected(
        AnchorIn("story", story.id, story.title, None), techniques, _to_in(rows), truncated=False
    )


async def collect_entity(
    session: AsyncSession, entity_id: int, *, days: int, max_tlp: str | None
) -> Collected:
    ent = await session.get(Entity, entity_id)
    if ent is None or ent.suppressed or ent.type not in ENTITY_ANCHOR_TYPES:
        raise AnchorNotFound(f"entity {entity_id}")
    if ent.merged_into_id is not None:
        raise AnchorMerged(ent.merged_into_id)
    anchor = AnchorIn("entity", ent.id, ent.name, ent.type)
    if ent.type == "attack-pattern":
        # pack Sigma saja: teknik itu sendiri, tanpa indikator
        own = [TechniqueIn(ent.external_id, ent.name, "primary")] if ent.external_id else []
        return Collected(anchor, own, [], truncated=False)

    target = aliased(Entity)
    tech_rows = await session.execute(
        select(target.external_id, target.name)
        .join(Relationship, Relationship.target_entity_id == target.id)
        .where(
            Relationship.source_entity_id == entity_id,
            Relationship.relationship_type == "uses",
            Relationship.revoked_at.is_(None),
            Relationship.provenance.in_(("attack", "analyst")),
            target.type == "attack-pattern",
            target.merged_into_id.is_(None),
            target.suppressed.is_(False),
            target.external_id.is_not(None),
        )
    )
    techniques = [TechniqueIn(r.external_id, r.name, "primary") for r in tech_rows]

    now = datetime.datetime.now(datetime.UTC)
    since = now - datetime.timedelta(days=days)
    article_day = func.coalesce(Article.posted_on, cast(Article.created_at, Date))
    from_articles = (
        select(IndicatorSource.indicator_id)
        .join(Article, Article.id == IndicatorSource.article_id)
        .outerjoin(Story, Story.id == Article.story_id)
        .where(
            exists().where(
                EntityMention.article_id == Article.id, EntityMention.entity_id == entity_id
            ),
            or_(
                Story.last_seen_at >= since,
                and_(Article.story_id.is_(None), article_day >= since.date()),
            ),
        )
    )
    from_relationships = select(Relationship.source_indicator_id).where(
        Relationship.target_entity_id == entity_id,
        Relationship.relationship_type == "indicates",
        Relationship.revoked_at.is_(None),
        Relationship.source_indicator_id.is_not(None),
    )
    rows = (
        await session.execute(
            _indicator_select(max_tlp)
            .where(Indicator.id.in_(union(from_articles, from_relationships)))
            .order_by(Indicator.last_seen_at.desc(), Indicator.id.desc())
            .limit(ENTITY_INDICATOR_CAP + 1)
        )
    ).all()
    return Collected(
        anchor,
        techniques,
        _to_in(rows[:ENTITY_INDICATOR_CAP]),
        truncated=len(rows) > ENTITY_INDICATOR_CAP,
    )


async def _sigma_candidates(
    session: AsyncSession, techniques: list[TechniqueIn], include: set[str]
) -> list[SigmaIn]:
    """Rule kandidat: tag beririsan dengan id teknik + induk sub-teknik (GIN `&&`), ditambah rule
    yang hanya memberi tag sub-teknik dari teknik induk di pack. `select_sigma` memfilter akhir."""
    ids = {t.attack_id for t in merge_tiers(techniques) if t.tier == "primary" or t.tier in include}
    if not ids:
        return []
    exact = sorted(ids | {i.split(".")[0] for i in ids})
    children = [f"{i}.%" for i in sorted(ids) if "." not in i]
    tag = column("t", String)
    conds = [SigmaRule.techniques.overlap(array(exact))]
    if children:
        conds.append(
            exists(
                select(1)
                .select_from(func.unnest(SigmaRule.techniques).alias("t"))
                .where(or_(*(tag.like(p) for p in children)))
            )
        )
    rows = await session.execute(
        select(
            SigmaRule.id,
            SigmaRule.title,
            SigmaRule.level,
            SigmaRule.status,
            SigmaRule.author,
            SigmaRule.ruleset,
            SigmaRule.path,
            SigmaRule.release,
            SigmaRule.techniques,
            SigmaRule.logsource,
        ).where(or_(*conds))
    )
    return [
        SigmaIn(
            str(r.id), r.title, r.level, r.status, r.author, r.ruleset, r.path, r.release,
            tuple(r.techniques), r.logsource,
        )
        for r in rows
    ]  # fmt: skip


async def get_pack(
    session: AsyncSession,
    anchor_type: Literal["story", "entity"],
    anchor_id: int,
    *,
    include: set[str],
    days: int,
    max_tlp: str | None,
) -> HuntPack:
    if anchor_type == "story":
        c = await collect_story(session, anchor_id, max_tlp=max_tlp)
    else:
        c = await collect_entity(session, anchor_id, days=days, max_tlp=max_tlp)
    snap = await session.get(ReferenceSnapshot, SIGMA_SNAPSHOT)
    release = snap.content.get("release") if snap is not None else None
    return build_pack(
        c.anchor,
        c.techniques,
        c.indicators,
        await _sigma_candidates(session, c.techniques, include),
        include=include,
        sigma_release=release,
        truncated=c.truncated,
        now=datetime.datetime.now(datetime.UTC),
    )


async def get_pack_zip(
    session: AsyncSession,
    anchor_type: Literal["story", "entity"],
    anchor_id: int,
    *,
    include: set[str],
    days: int,
    max_tlp: str | None,
) -> bytes:
    pack = await get_pack(
        session, anchor_type, anchor_id, include=include, days=days, max_tlp=max_tlp
    )
    yaml_rows = await session.execute(
        select(SigmaRule.id, SigmaRule.yaml).where(
            SigmaRule.id.in_([uuid.UUID(m.id) for m in pack.sigma])
        )
    )
    sigma_yaml = {str(r.id): r.yaml for r in yaml_rows}
    return pack_zip(pack, sigma_yaml, LICENSE_FILE.read_text(encoding="utf-8"))
