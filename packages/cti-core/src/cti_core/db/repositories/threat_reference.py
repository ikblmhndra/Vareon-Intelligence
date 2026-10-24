"""Baca (bukan tulis) `threat_actor_groups`/`monitored_people` -- lihat
`db/models/threat_reference.py` buat kenapa dua tabel ini ada dan kenapa
kosong sampai di-seed."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cti_core.db.models.attack import AttackGroup, AttackSoftware
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
