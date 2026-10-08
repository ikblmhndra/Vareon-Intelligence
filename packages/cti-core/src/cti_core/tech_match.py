"""Satu pencocok nama tech -- `docs/ROADMAP.md` #19, latar belakang di `docs/CVE_TECH_MATCHING.md`.

Dulu nama techstack (`techstack_entries.name`, teks bebas) dicocokkan oleh banyak tempat dengan
aturan berbeda: gate `new_cve`, filter Tenable, `score.py` (`related_tech_status` dengan
`\\b{tech}\\b` tanpa `re.escape`, `check_tech_stack` dengan substring tanpa batas kata), dan
`cve_priority.in_tech_stack` (substring dua arah). Akibatnya satu nama bisa "cocok" di satu
tempat dan tidak di tempat lain, dan tech pendek (`go`, `edge`) cocok ke kata yang cuma
mengandung hurufnya. Modul ini satu-satunya definisi "teks ini menyebut tech itu" untuk
pemanggil-pemanggil itu.

Aturan (diangkat apa adanya dari gate `new_cve` 0.2.1 + koreksi `f96d23b`):
- Huruf kecil, semua non-alfanumerik jadi satu spasi: `Palo_Alto-Networks` = `palo alto networks`,
  `Node.js` = `node js`.
- Tech harus muncul sebagai KATA UTUH (urutan kata dijaga). `nginx` tidak cocok dengan `nginxy`
  atau `nginxplus`, `go` tidak cocok dengan `google`.
- Angka (maks 4 digit) yang menempel di ujung dianggap versi mayor produk yang sama:
  `graylog2-server` cocok dengan `graylog`, `Log4j2` dengan `log4j`. Huruf yang menempel tidak.
- Istilah yang setelah dinormalisasi kurang dari 2 karakter (mis. nama `c++` -> `c`) TIDAK pernah
  cocok. Lebih baik tidak cocok daripada cocok ke setiap huruf `c` yang berdiri sendiri.

Yang sengaja BUKAN tugas modul ini: menemukan kandidat CVE (`keywordSearch` NVD / Tenable tetap
memakai nama tech apa adanya), alias nama lain (dibuang 2026-10-07; identitas produk nanti datang
dari katalog, `docs/ROADMAP.md` #19), dan hierarki produk (Outlook di bawah Microsoft 365).

Tidak memakai modul ini, PENGECUALIAN DISENGAJA (keputusan 2026-10-08):
`reports/cve_record.py::applicable_to_stack` (laporan Top CVE). Tesnya (`test_cve_record.py`)
mengunci `c++` ~ `c++ inc`, yang bertentangan dengan aturan istilah pendek di atas; jangan disatukan
sebagai "perapian".
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

_MIN_TERM_LEN = 2
_RE_ALNUM = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> str:
    """Huruf kecil, semua non-alfanumerik jadi satu spasi -- bentuk yang dibandingkan."""
    return " ".join(_RE_ALNUM.findall(text.lower()))


@lru_cache(maxsize=4096)
def _compiled(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(term)}[0-9]{{0,4}}(?![a-z0-9])")


def _term(name: str) -> str | None:
    term = normalize(name)
    return term if len(term) >= _MIN_TERM_LEN else None


def mentions(name: str, text: str) -> bool:
    """`name` muncul sebagai kata utuh di `text`."""
    term = _term(name)
    return term is not None and _compiled(term).search(normalize(text)) is not None


def matching_names(names: Iterable[str], text: str) -> list[str]:
    """Subset `names` yang disebut `text`, urutan masukan dijaga. `text` dinormalisasi SEKALI --
    dipakai pemanggil yang menyaring puluhan tech terhadap satu judul/ringkasan."""
    haystack = normalize(text)
    if not haystack:
        return []
    out: list[str] = []
    for n in names:
        term = _term(n)
        if term is not None and _compiled(term).search(haystack):
            out.append(n)
    return out


def mentions_any(names: Iterable[str], text: str) -> bool:
    """Ada tech di `names` yang disebut `text`."""
    return bool(matching_names(names, text))


# Isian "produk" yang bukan nama produk -- CNA kadang mengisi ini kalau tak punya data.
_PLACEHOLDER_PRODUCTS = frozenset({"", "n a", "na", "none", "unknown", "unspecified", "various"})


def usable_products(products: list[str]) -> list[str]:
    """`products` tanpa isian placeholder ("n/a", "unknown", ...)."""
    return [p for p in products if normalize(p) not in _PLACEHOLDER_PRODUCTS]


def relevant_techs(techs: list[str], summary: str, products: list[str]) -> list[str]:
    """Subset `techs` yang beneran terdampak. `products` = vendor/product/packageName/CPE dari
    record MITRE; kalau CNA tak mengisinya sama sekali baru jatuh ke ringkasan (satu-satunya
    petunjuk yang tersisa). Gate teks `new_cve`, dan jalur entri tanpa target di promosi mirror
    (`cti_core.cve_promotion`); pindah ke sini supaya keduanya satu definisi."""
    haystacks = usable_products(products) or [summary]
    return [t for t in techs if any(mentions(t, h) for h in haystacks)]
