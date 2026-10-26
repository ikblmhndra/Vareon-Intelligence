"""Baca (bukan tulis) `threat_actor_groups`/`monitored_people` -- lihat
`db/models/threat_reference.py` buat kenapa dua tabel ini ada dan kenapa
kosong sampai di-seed."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cti_core.db.models.attack import AttackGroup, AttackSoftware
from cti_core.db.models.ta import TAWhitelistEntry
from cti_core.db.models.threat_reference import MonitoredPerson, ThreatActorGroup


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


def load_entity_sources(
    session: Session,
) -> tuple[list[tuple[str, list[str]]], list[tuple[str, str, list[str]]], list[str], list[str]]:
    """Bahan mentah kamus entitas tier 1: (grup ATT&CK, software ATT&CK, nama
    `threat_actor_groups`, nama `ta_whitelist`). `ta_whitelist` = daftar nama yang SENGAJA
    ditolak jadi aktor (huruf kecil), jadi dilempar ke `build_dictionary` sebagai `suppressed`."""
    groups = [
        (name, list(aliases or []))
        for name, aliases in session.execute(select(AttackGroup.name, AttackGroup.aliases)).all()
    ]
    software = [
        (name, software_type, list(aliases or []))
        for name, software_type, aliases in session.execute(
            select(AttackSoftware.name, AttackSoftware.software_type, AttackSoftware.aliases)
        ).all()
    ]
    ta_names = list(session.execute(select(ThreatActorGroup.name)).scalars().all())
    suppressed = list(session.execute(select(TAWhitelistEntry.name)).scalars().all())
    return groups, software, ta_names, suppressed
