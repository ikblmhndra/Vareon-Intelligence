"""Seed entitas untuk test integrasi (P7c Task 8): kamus Tier 1 dibangun dari `entity_aliases`,
jadi test yang dulu mengisi `attack_groups`/`attack_software` kini mengisi entitas + alias."""

from __future__ import annotations

from cti_core.db.models.entity import Entity, EntityAlias
from cti_core.entity import alias_norm, entity_stix_id
from cti_core.entity.mentions import MentionInput, insert_mentions, mention_rows, resolve_all
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


def add_subject_mentions(
    s: Session, subject: dict[str, int], hits: list[MentionInput], method: str = "legacy"
) -> None:
    """Mention untuk subjek non-artikel (mis. `{"cve_tracker_id": 1}`) lewat resolver -- pengganti
    `CveTracker.threat_actors`/`ttps` lama di seed test (P7c Task 12). `hits` dengan method
    kosong memakai `method`. Relasi `mentions` objek yang SUDAH dimuat tidak di-refresh."""
    resolved = resolve_all(
        s, [h if h.method else MentionInput(**{**h.__dict__, "method": method}) for h in hits]
    )
    rows = mention_rows(subject, resolved)
    if rows:
        s.execute(insert_mentions(rows, update=False))
    s.flush()


def actor(name: str) -> MentionInput:
    return MentionInput("intrusion-set", name, "", name)


def technique(ttp_id: str, name: str) -> MentionInput:
    return MentionInput("attack-pattern", name, "", ttp_id, external_id=ttp_id)
