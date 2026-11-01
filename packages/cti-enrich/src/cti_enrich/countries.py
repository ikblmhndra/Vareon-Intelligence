"""Nama negara (Inggris, hasil GPT/regex) -> kode ISO 3166-1 alpha-2 --
mention negara (`entities.external_id`) minta kode, bukan nama, tapi kode
lama (Mongo `apac-country`/`global-country`) cuma nyimpen nama. Lihat
catatan "Perubahan yang disengaja" di `stages/score.py`.

`pycountry.lookup()` + `search_fuzzy()` nangkep hampir semua nama umum
("Russia" -> RUS, "Brunei" -> BRN, dst) -- `_ALIASES` cuma buat sisa
yang gak ketemu dua-duanya (dicek langsung: cuma "Ivory Coast", pycountry
resminya "Côte d'Ivoire" dan fuzzy search gak nangkep nama Inggris umum
itu). Nama yang tetep gak ketemu di-skip (bukan raise) -- caller
(`stages/persist.py`) log warning, konsisten sama pola `new_cve.py`
(Fase 4) skip tech tanpa client match daripada nebak fallback."""

from __future__ import annotations

import pycountry

_ALIASES = {
    "ivory coast": "CI",
}


def country_code(name: str) -> str | None:
    key = name.strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    try:
        return pycountry.countries.lookup(name).alpha_2
    except LookupError:
        pass
    try:
        results = pycountry.countries.search_fuzzy(name)
        return results[0].alpha_2 if results else None
    except LookupError:
        return None
