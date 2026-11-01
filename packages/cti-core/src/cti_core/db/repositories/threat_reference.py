"""Baca (bukan tulis) `threat_actor_groups`/`monitored_people` -- lihat
`db/models/threat_reference.py` buat kenapa dua tabel ini ada dan kenapa
kosong sampai di-seed."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cti_core.db.models.attack import AttackGroup, AttackSoftware
from cti_core.db.models.entity import Entity, EntityAlias
from cti_core.db.models.threat_reference import MonitoredPerson, ThreatActorGroup
from cti_core.entity import alias_norm


def list_threat_actor_groups(session: Session) -> list[str]:
    """Nama grup TA untuk dicocokkan di teks, MINUS nama yang menurut ATT&CK adalah software
    (malware/tool) dan bukan grup. Daftar malpedia/threat-card memuat "Cobalt strike", jadi tiap
    artikel yang menyebut tool itu tercatat punya aktor "Cobalt strike" (audit UI U8)."""
    software = set(list_non_actor_software_names(session))
    names = session.execute(select(ThreatActorGroup.name)).scalars().all()
    return sorted(n for n in names if n.lower() not in software)


def list_non_actor_software_names(session: Session) -> list[str]:
    """Nama + alias software ATT&CK (huruf kecil) yang BUKAN nama/alias grup ATT&CK. Dipakai dua
    kali: dibuang dari daftar aktor, dan di-mask dari teks sebelum aktor dicocokkan supaya grup
    "Cobalt" tidak cocok di dalam "Cobalt Strike". Kosong sampai sync ATT&CK pertama."""
    groups: set[str] = set()
    for name, aliases in session.execute(select(AttackGroup.name, AttackGroup.aliases)).all():
        groups.update(a.lower() for a in (name, *(aliases or [])) if a)
    software: set[str] = set()
    for name, aliases in session.execute(select(AttackSoftware.name, AttackSoftware.aliases)).all():
        software.update(a.lower() for a in (name, *(aliases or [])) if a)
    return sorted(software - groups)


def list_monitored_people(session: Session) -> list[str]:
    return sorted(session.execute(select(MonitoredPerson.name)).scalars().all())


_DICT_TYPES = ("intrusion-set", "malware", "tool")
_CURATED_ALIAS_SOURCES = frozenset({"attack", "galaxy", "analyst"})

AliasRow = tuple[str, str, str, bool]
"""`(alias, nama kanonik entitas, tipe entitas, alias ATT&CK?)` -- bahan kamus Tier 1."""


def load_entity_sources(session: Session) -> tuple[list[AliasRow], list[str], list[str]]:
    """Bahan mentah kamus entitas Tier 1 (P7c, spec 4.3): alias entitas hidup (tidak suppressed,
    bukan tombstone) bertipe aktor/malware/tool dengan nama kanonik = `entities.name`, nama
    `threat_actor_groups` (yang belum jadi alias disaring `build_entity_dictionary`), dan alias
    entitas suppressed (pengganti `ta_whitelist`: tidak pernah dicocokkan dari sumber mana pun).

    Alias bersumber `legacy`/`dictionary` hanya ikut bila namanya juga ada di
    `threat_actor_groups`: nama yang cuma dikenal dari data lama atau grup ransomware ("Payload",
    dev 2026-11-01) cocok dengan kata biasa di artikel. Cakupan kamus = P4 + Galaxy + analis.
    """
    rows = session.execute(
        select(EntityAlias.alias, Entity.name, Entity.type, EntityAlias.source, Entity.suppressed)
        .join(Entity, Entity.id == EntityAlias.entity_id)
        .where(Entity.type.in_(_DICT_TYPES), Entity.merged_into_id.is_(None))
        .order_by(EntityAlias.id)
    ).all()
    ta_names = list(session.execute(select(ThreatActorGroup.name)).scalars().all())
    ta_norms = {alias_norm(n) for n in ta_names}
    aliases = [
        (a, name, typ, src == "attack")
        for a, name, typ, src, sup in rows
        if not sup and (src in _CURATED_ALIAS_SOURCES or alias_norm(a) in ta_norms)
    ]
    suppressed = [a for a, _, _, _, sup in rows if sup]
    return aliases, ta_names, suppressed
