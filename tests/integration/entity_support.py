"""Seed entitas untuk test integrasi (P7c Task 8): kamus Tier 1 dibangun dari `entity_aliases`,
jadi test yang dulu mengisi `attack_groups`/`attack_software` kini mengisi entitas + alias."""

from __future__ import annotations

from cti_core.db.models.entity import Entity, EntityAlias
from cti_core.entity import alias_norm, entity_stix_id
from sqlalchemy.orm import Session


def seed_entity(
    s: Session,
    type_: str,
    name: str,
    *aliases: str,
    source: str = "attack",
    alias_source: str | None = None,
    external_id: str | None = None,
) -> Entity:
    """Entitas hidup + alias nama sendiri (+ alias tambahan). Default meniru objek ATT&CK."""
    key = external_id.upper() if type_ == "attack-pattern" and external_id else name
    ent = Entity(
        type=type_,
        stix_id=entity_stix_id(type_, key),
        name=name,
        source=source,
        external_id=external_id,
    )
    s.add(ent)
    s.flush()
    own = [key] if type_ == "attack-pattern" else [name]
    for alias in [*own, *aliases]:
        s.add(
            EntityAlias(
                entity_id=ent.id,
                entity_type=type_,
                alias=alias,
                alias_norm=alias_norm(alias),
                source=alias_source or source,
            )
        )
    s.flush()
    return ent
