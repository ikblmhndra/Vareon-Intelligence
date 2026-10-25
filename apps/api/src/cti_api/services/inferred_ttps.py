"""Teknik ATT&CK yang DIKAITKAN ke aktor/malware sebuah artikel (P4).

Nama aktor (`article.threat_actors`) dan malware/tool (`article.malware`) dicocokkan
case-insensitive ke nama atau alias `attack_groups` / `attack_software` (nama aktor tersimpan
sudah `capitalize()`, mis. "Apt29"). Teknik diambil dari relasi `uses` -> `attack-pattern`.
Hasil TIDAK disimpan: ini inferensi dari katalog, bukan klaim artikel, jadi tampil terpisah
dari `article_ttps`. Entitas tanpa kecocokan ATT&CK dilewati."""

from __future__ import annotations

from collections.abc import Sequence

from cti_core.db.models.article import Article
from cti_core.db.models.attack import (
    AttackGroup,
    AttackRelationship,
    AttackSoftware,
    AttackTechnique,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.schemas.article import InferredEntity, InferredTechnique


def _index(
    rows: Sequence[tuple[str, str, str, list[str]]],
) -> dict[str, tuple[str, str]]:
    """lowercase(nama|alias) -> (stix_id, attack_id); nama resmi menang atas alias."""
    by_name: dict[str, tuple[str, str]] = {}
    for stix_id, attack_id, name, _ in rows:
        by_name[name.lower()] = (stix_id, attack_id)
    for stix_id, attack_id, _, aliases in rows:
        for alias in aliases:
            by_name.setdefault(alias.lower(), (stix_id, attack_id))
    return by_name


async def for_article(session: AsyncSession, article: Article) -> list[InferredEntity]:
    actors = [t.threat_actor for t in article.threat_actors]
    if not actors and not article.malware:
        return []

    groups = (
        await session.execute(
            select(AttackGroup.stix_id, AttackGroup.group_id, AttackGroup.name, AttackGroup.aliases)
        )
    ).all()
    software = (
        await session.execute(
            select(
                AttackSoftware.stix_id,
                AttackSoftware.software_id,
                AttackSoftware.name,
                AttackSoftware.aliases,
            )
        )
    ).all()
    group_index = _index([(r[0], r[1], r[2], list(r[3])) for r in groups])
    software_index = _index([(r[0], r[1], r[2], list(r[3])) for r in software])

    # (entity, kind, stix_id, attack_id), urut: aktor lalu malware/tool, sesuai urutan artikel
    matched: list[tuple[str, str, str, str]] = []
    for actor in actors:
        hit = group_index.get(actor.lower())
        if hit:
            matched.append((actor, "actor", hit[0], hit[1]))
    for m in article.malware:
        hit = software_index.get(m.name.lower())
        if hit:
            matched.append((m.name, m.kind, hit[0], hit[1]))
    if not matched:
        return []

    rels = (
        await session.execute(
            select(AttackRelationship.source_ref, AttackTechnique.attack_id, AttackTechnique.name)
            .join(AttackTechnique, AttackTechnique.stix_id == AttackRelationship.target_ref)
            .where(
                AttackRelationship.relationship_type == "uses",
                AttackRelationship.target_type == "attack-pattern",
                AttackRelationship.source_ref.in_({m[2] for m in matched}),
            )
        )
    ).all()
    techniques: dict[str, dict[str, str]] = {}
    for source_ref, attack_id, name in rels:
        techniques.setdefault(source_ref, {})[attack_id] = name

    out: list[InferredEntity] = []
    for entity, kind, stix_id, attack_id in matched:
        techs = techniques.get(stix_id, {})
        if not techs:
            continue
        out.append(
            InferredEntity(
                entity=entity,
                kind=kind,  # type: ignore[arg-type]
                attack_id=attack_id,
                techniques=[InferredTechnique(id=i, name=techs[i]) for i in sorted(techs)],
            )
        )
    return out
