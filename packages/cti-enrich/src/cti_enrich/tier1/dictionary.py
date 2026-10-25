"""Kamus entitas tier 1: gabungan grup/software ATT&CK + `threat_actor_groups`.

Pure: gak ada Session/HTTP/spaCy. Pemanggil (stage) yang baca tabel lalu ngasih
datanya ke `build_dictionary`, jadi kamus gampang dites dan di-cache per proses.

Aturan gabung (ATT&CK menang karena kurasinya lebih ketat, dan supaya "Cobalt
Strike" gak kecatat sebagai aktor "Cobalt" -- audit UI U8):
- grup ATT&CK -> actor, canonical = nama ATT&CK;
- software ATT&CK -> malware/tool menurut `software_type`, KECUALI nama/alias
  yang sama juga nama grup (mis. "Lazarus Group") -> tetap actor;
- nama `threat_actor_groups` -> actor, dibuang kalau namanya software ATT&CK,
  dilewati kalau key-nya sudah ada;
- nama di `suppressed` (`ta_whitelist`) dibuang dari mana pun asalnya.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from cti_enrich.tier1.entities import AMBIGUOUS

Kind = Literal["actor", "malware", "tool"]

# Nama pendek / huruf kapital semua ("APT29", "FIN7") gampang bentrok dengan kata
# biasa kalau dicocokkan tanpa peduli huruf besar.
_SHORT_NAME = 4


@dataclass(frozen=True)
class Entity:
    canonical: str
    kind: Kind
    needs_context: bool
    case_sensitive: bool


@dataclass(frozen=True)
class EntityDictionary:
    # Key = nama apa adanya untuk entri case-sensitive, huruf kecil untuk sisanya.
    entries: Mapping[str, Entity]
    # 8 hex pertama sha256 dari key terurut; stabil terhadap urutan input.
    version: str


def _is_case_sensitive(term: str) -> bool:
    return len(term) <= _SHORT_NAME or term.isupper()


def _is_single_token(lowered: str) -> bool:
    return re.fullmatch(r"[a-z]+", lowered) is not None


def build_dictionary(
    groups: Iterable[tuple[str, Sequence[str]]],
    software: Iterable[tuple[str, str, Sequence[str]]],
    ta_names: Iterable[str],
    suppressed: Iterable[str],
) -> EntityDictionary:
    blocked = {s.lower() for s in suppressed}
    entries: dict[str, Entity] = {}

    def add(term: str, canonical: str, kind: Kind, *, from_ta_only: bool = False) -> None:
        lowered = term.lower()
        if not term or lowered in blocked:
            return
        case_sensitive = False if from_ta_only else _is_case_sensitive(term)
        key = term if case_sensitive else lowered
        if key in entries:
            return
        needs_context = lowered in AMBIGUOUS or (from_ta_only and _is_single_token(lowered))
        entries[key] = Entity(canonical, kind, needs_context, case_sensitive)

    group_list = [(name, list(aliases)) for name, aliases in groups]
    group_terms = {t.lower() for name, aliases in group_list for t in (name, *aliases)}

    for name, aliases in group_list:
        for term in (name, *aliases):
            add(term, name, "actor")

    software_list = [(n, t, list(a)) for n, t, a in software]
    software_terms = {term.lower() for n, _, a in software_list for term in (n, *a)}
    for name, software_type, aliases in software_list:
        kind: Kind = "tool" if software_type == "tool" else "malware"
        for term in (name, *aliases):
            if term.lower() in group_terms:
                continue  # sudah masuk sebagai actor di atas
            add(term, name, kind)

    for name in ta_names:
        # ATT&CK menang, juga untuk key case-sensitive ('APT29' vs 'apt29').
        if name.lower() in software_terms or name.lower() in group_terms:
            continue
        add(name, name, "actor", from_ta_only=True)

    digest = hashlib.sha256("\n".join(sorted(entries)).encode()).hexdigest()[:8]
    return EntityDictionary(entries=entries, version=digest)
