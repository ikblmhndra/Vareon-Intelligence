"""Pengelompokan negara per wilayah yang dipakai lintas paket (ROADMAP #22, PR 7).

Isinya cuma `APAC_COUNTRY_CODES`. Sebelum modul ini TIDAK ADA definisi "negara APAC" di kode mana
pun: `stages/score.py` memakai `pycountry` (SEMUA negara ISO) sebagai daftar negara, jadi
`Article.news_type == "apac"` artinya "cabang regional" (artikel menyebut negara apa pun dan tidak
jatuh ke kategori khusus), bukan "menyebut negara Asia-Pasifik". Daftar kuratif lama (`apac-country`
di Mongo) tidak pernah ikut diport (docs/PROGRESS.md, 5.5) dan dumpnya tidak ada di repo. Newsletter
butuh definisi yang bisa diperiksa mesin untuk menaruh artikel di section Asia Pacific, maka
konstanta minimal ini dibuat di `cti_core` (bukan di `cti_api`) supaya paket lain bisa memakai
definisi yang sama dan API tidak perlu mengimpor `cti_enrich`.

Acuannya pengelompokan Bank Dunia "East Asia & Pacific" ditambah "South Asia", kode ISO 3166-1
alpha-2 huruf besar (format `ArticleCountry.country_code` dan `ClientCountry.country_code`).
SENGAJA tidak termasuk: Asia Tengah, Timur Tengah, dan Rusia. Ini titik mulai yang bisa digeser
analis setelah edisi pertama; menambah atau mengurangi kode di sini langsung mengubah section
saran newsletter, tanpa migrasi."""

from __future__ import annotations

APAC_COUNTRY_CODES: frozenset[str] = frozenset(
    {
        # Asia Timur
        "CN", "HK", "JP", "KP", "KR", "MN", "MO", "TW",
        # Asia Tenggara
        "BN", "ID", "KH", "LA", "MM", "MY", "PH", "SG", "TH", "TL", "VN",
        # Asia Selatan
        "AF", "BD", "BT", "IN", "LK", "MV", "NP", "PK",
        # Oseania dan Pasifik
        "AS", "AU", "FJ", "FM", "GU", "KI", "MH", "MP", "NC", "NR", "NZ", "PF", "PG", "PW", "SB",
        "TO", "TV", "VU", "WS",
    }
)  # fmt: skip
