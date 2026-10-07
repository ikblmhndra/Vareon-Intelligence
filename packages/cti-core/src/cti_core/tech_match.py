"""Satu pencocok nama tech -- `docs/ROADMAP.md` #19 fase 1, latar belakang di
`docs/CVE_TECH_MATCHING.md`.

Dulu nama techstack (`techstack_entries.name`, teks bebas) dicocokkan oleh ENAM tempat dengan aturan
berbeda: gate `new_cve`, filter Tenable, `score.py` (`related_tech_status` dengan
`\\b{tech}\\b` tanpa `re.escape`, `check_tech_stack` dengan substring tanpa batas kata), dan
`cve_priority.in_tech_stack` (substring dua arah). Akibatnya satu nama bisa "cocok" di satu
tempat dan tidak di tempat lain, dan tech pendek (`go`, `edge`) cocok ke kata yang cuma
mengandung hurufnya. Modul ini satu-satunya definisi "teks ini menyebut tech itu"; semua
pemanggil memakainya.

Aturan (diangkat apa adanya dari gate `new_cve` 0.2.1 + koreksi `f96d23b`):
- Huruf kecil, semua non-alfanumerik jadi satu spasi: `Palo_Alto-Networks` = `palo alto networks`,
  `Node.js` = `node js`.
- Tech harus muncul sebagai KATA UTUH (urutan kata dijaga). `nginx` tidak cocok dengan `nginxy`
  atau `nginxplus`, `go` tidak cocok dengan `google`.
- Angka (maks 4 digit) yang menempel di ujung dianggap versi mayor produk yang sama:
  `graylog2-server` cocok dengan `graylog`, `Log4j2` dengan `log4j`. Huruf yang menempel tidak.
- **Alias**: satu tech boleh punya nama lain (`palo alto` -> `pan-os`, `paloaltonetworks`;
  `mikrotik` -> `routeros`) yang diperlakukan sama persis dengan namanya. Ini yang menutup kasus
  vendor/produk ditulis CNA dengan nama yang beda dari nama tech.
- Istilah yang setelah dinormalisasi kurang dari 2 karakter (mis. nama `c++` -> `c`) TIDAK pernah
  cocok. Lebih baik tidak cocok daripada cocok ke setiap huruf `c` yang berdiri sendiri.

Yang sengaja BUKAN tugas modul ini: menemukan kandidat CVE (`keywordSearch` NVD / Tenable tetap
memakai nama tech apa adanya), dan hierarki produk (Outlook di bawah Microsoft 365, fase 3).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache

AliasMap = Mapping[str, Sequence[str]]
"""Alias per tech. KUNCI = `normalize(nama tech)`, supaya `Palo Alto` dan `palo_alto` ketemu."""

_MIN_TERM_LEN = 2
_RE_ALNUM = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> str:
    """Huruf kecil, semua non-alfanumerik jadi satu spasi -- bentuk yang dibandingkan."""
    return " ".join(_RE_ALNUM.findall(text.lower()))


def terms(name: str, aliases: Iterable[str] = ()) -> tuple[str, ...]:
    """`name` + `aliases` dalam bentuk ternormalisasi: tanpa duplikat, urutan stabil (nama dulu),
    istilah terlalu pendek dibuang (lihat docstring modul)."""
    out: dict[str, None] = {}
    for raw in (name, *aliases):
        term = normalize(raw)
        if len(term) >= _MIN_TERM_LEN:
            out[term] = None
    return tuple(out)


def aliases_of(name: str, alias_map: AliasMap | None) -> Sequence[str]:
    """Alias milik `name` dari `alias_map` (kunci = `normalize(name)`); kosong kalau tak ada."""
    if not alias_map:
        return ()
    return alias_map.get(normalize(name), ())


def build_alias_map(rows: Iterable[tuple[str, Iterable[str] | None]]) -> dict[str, list[str]]:
    """Baris `(nama tech, aliases)` -> `AliasMap`. GABUNGAN kalau nama yang sama muncul lagi (alias
    itu sifat produknya, bukan sifat client yang kebetulan memakainya); tech tanpa alias tidak
    masuk; kunci `normalize(nama)`. Murni -- pemanggil yang menjalankan `SELECT name, aliases`."""
    merged: dict[str, dict[str, None]] = {}
    for name, aliases in rows:
        if aliases:
            merged.setdefault(normalize(name), {}).update(dict.fromkeys(aliases))
    return {key: sorted(values) for key, values in sorted(merged.items())}


@lru_cache(maxsize=4096)
def _compiled(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(term)}[0-9]{{0,4}}(?![a-z0-9])")


def _hits(term_list: Iterable[str], normalized_text: str) -> bool:
    return any(_compiled(t).search(normalized_text) for t in term_list)


def mentions(name: str, text: str, aliases: Iterable[str] = ()) -> bool:
    """`name` (atau salah satu `aliases`-nya) muncul sebagai kata utuh di `text`."""
    return _hits(terms(name, aliases), normalize(text))


def matching_names(names: Iterable[str], text: str, alias_map: AliasMap | None = None) -> list[str]:
    """Subset `names` yang disebut `text`, urutan masukan dijaga. `text` dinormalisasi SEKALI --
    dipakai pemanggil yang menyaring puluhan tech terhadap satu judul/ringkasan."""
    haystack = normalize(text)
    if not haystack:
        return []
    return [n for n in names if _hits(terms(n, aliases_of(n, alias_map)), haystack)]


def mentions_any(names: Iterable[str], text: str, alias_map: AliasMap | None = None) -> bool:
    """Ada tech di `names` yang disebut `text`."""
    haystack = normalize(text)
    return bool(haystack) and any(
        _hits(terms(n, aliases_of(n, alias_map)), haystack) for n in names
    )
