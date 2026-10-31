"""Kamus entitas tier 1: alias entitas (`entity_aliases`, P7c) + `threat_actor_groups`.

Pure: gak ada Session/HTTP/spaCy. Pemanggil (stage) yang baca tabel lalu ngasih
datanya ke `build_dictionary`, jadi kamus gampang dites dan di-cache per proses.

Aturan gabung (ATT&CK menang karena kurasinya lebih ketat, dan supaya "Cobalt
Strike" gak kecatat sebagai aktor "Cobalt" -- audit UI U8):
- grup ATT&CK -> actor, canonical = nama ATT&CK;
- software ATT&CK -> malware/tool menurut `software_type`, KECUALI nama/alias
  yang sama juga nama grup (mis. "Lazarus Group") -> tetap actor;
- nama `threat_actor_groups` -> actor, dibuang kalau namanya software ATT&CK,
  dilewati kalau key-nya sudah ada;
- nama di `suppressed` (alias entitas suppressed, dulu `ta_whitelist`) dibuang dari mana pun.

Sejak P7c (spec 4.3) bahan utamanya `entity_aliases` (`build_entity_dictionary`): alias ATT&CK
diperlakukan seperti grup/software ATT&CK di atas, alias lain (Galaxy, legacy, ...) seperti nama
`threat_actor_groups` (Ruling 23).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from cti_core.entity.ambiguous import is_single_token as _is_single_token

from cti_enrich.tier1.entities import AMBIGUOUS, WINDOWS_UTILITY_NAMES

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


_KIND_OF_TYPE: dict[str, Kind] = {"intrusion-set": "actor", "malware": "malware", "tool": "tool"}


@dataclass(frozen=True)
class _Term:
    term: str
    canonical: str
    kind: Kind
    curated: bool
    """Alias ATT&CK: huruf besar-kecil menurut `_is_case_sensitive`, kata konteks hanya untuk
    `AMBIGUOUS`. Selain itu (nama `threat_actor_groups`, alias Galaxy/legacy/dictionary/analis)
    tidak case-sensitive dan nama satu kata butuh kata konteks (aturan P4, Ruling 23)."""


def _build(
    terms: Sequence[_Term],
    ta_names: Iterable[str],
    suppressed: Iterable[str],
    *,
    ta_needs_context: bool,
) -> EntityDictionary:
    """Urutan prioritas (key pertama menang): aktor ATT&CK, software ATT&CK (kecuali term grup
    ATT&CK), aktor lain (kecuali term software ATT&CK), software lain (kecuali term aktor mana
    pun), lalu nama `threat_actor_groups` yang belum jadi term apa pun."""
    blocked = {s.lower() for s in suppressed}
    entries: dict[str, Entity] = {}

    def add(term: str, canonical: str, kind: Kind, *, curated: bool, from_ta: bool) -> None:
        lowered = term.lower()
        if not term or lowered in blocked:
            return
        case_sensitive = curated and _is_case_sensitive(term)
        key = term if case_sensitive else lowered
        if key in entries:
            return
        if from_ta and not ta_needs_context:
            needs_context = False  # daftar kurasi pemanggil: AMBIGUOUS pun tidak (Ruling 18)
        else:
            needs_context = lowered in AMBIGUOUS or (not curated and _is_single_token(lowered))
        entries[key] = Entity(canonical, kind, needs_context, case_sensitive)

    def lowered(curated: bool, actor: bool) -> set[str]:
        return {
            t.term.lower() for t in terms if t.curated == curated and (t.kind == "actor") == actor
        }

    attack_actor, attack_software = lowered(True, True), lowered(True, False)
    any_actor = attack_actor | lowered(False, True)
    all_terms = {t.term.lower() for t in terms}

    def software_term(t: _Term) -> str:
        # kata telanjang terlalu berisik; hanya "<nama>.exe"
        return f"{t.term}.exe" if t.term.lower() in WINDOWS_UTILITY_NAMES else t.term

    for curated in (True, False):
        for t in terms:
            if t.curated != curated or t.kind != "actor":
                continue
            if not curated and t.term.lower() in attack_software:
                continue
            add(t.term, t.canonical, "actor", curated=curated, from_ta=False)
        for t in terms:
            if t.curated != curated or t.kind == "actor":
                continue
            if t.term.lower() in (attack_actor if curated else any_actor):
                continue  # sudah masuk sebagai actor
            add(software_term(t), t.canonical, t.kind, curated=curated, from_ta=False)

    for name in ta_names:
        # ATT&CK/entitas menang, juga untuk key case-sensitive ('APT29' vs 'apt29').
        if name.lower() in all_terms:
            continue
        add(name, name, "actor", curated=False, from_ta=True)

    digest = hashlib.sha256("\n".join(sorted(entries)).encode()).hexdigest()[:8]
    return EntityDictionary(entries=entries, version=digest)


def build_dictionary(
    groups: Iterable[tuple[str, Sequence[str]]],
    software: Iterable[tuple[str, str, Sequence[str]]],
    ta_names: Iterable[str],
    suppressed: Iterable[str],
    *,
    ta_needs_context: bool = True,
) -> EntityDictionary:
    """Kamus dari daftar mentah grup/software ATT&CK. Dipakai pemanggil tanpa tabel entitas
    (`score` jalur tweet, eval, test). `ta_needs_context=False` dipakai pemanggil tanpa Session
    (monitor_x/tweet_alerts): daftar nama mereka sudah dikurasi, jadi nama dari `ta_names` tidak
    pernah diminta kata konteks -- baik nama satu kata ("turla") maupun yang ada di `AMBIGUOUS`
    ("akira"), sama seperti 0.8.x. Grup/software ATT&CK tetap memakai `AMBIGUOUS`."""
    terms: list[_Term] = []
    for name, aliases in groups:
        terms.extend(_Term(t, name, "actor", True) for t in (name, *aliases))
    for name, software_type, aliases in software:
        kind: Kind = "tool" if software_type == "tool" else "malware"
        terms.extend(_Term(t, name, kind, True) for t in (name, *aliases))
    return _build(terms, ta_names, suppressed, ta_needs_context=ta_needs_context)


def build_entity_dictionary(
    aliases: Iterable[tuple[str, str, str, bool]],
    ta_names: Iterable[str],
    suppressed: Iterable[str],
) -> EntityDictionary:
    """Kamus dari `entity_aliases` (P7c, spec 4.3; bahan dari
    `threat_reference.load_entity_sources`): `(alias, nama entitas, tipe entitas, alias ATT&CK?)`.
    Kanonik = `entities.name`, jadi hit "Cozy Bear" -> "APT29"; versi (hash key terurut) ikut
    berubah saat alias bertambah, sehingga cache proses ter-refresh oleh TTL berikutnya."""
    terms = [
        _Term(alias, name, _KIND_OF_TYPE[typ], curated)
        for alias, name, typ, curated in aliases
        if typ in _KIND_OF_TYPE
    ]
    return _build(terms, ta_names, suppressed, ta_needs_context=True)
