"""Unit test `cti_core.regions.APAC_COUNTRY_CODES` -- konstanta murni (ROADMAP #22, PR 7)."""

from __future__ import annotations

import pycountry
from cti_core.regions import APAC_COUNTRY_CODES


def test_every_code_is_a_real_uppercase_iso_alpha2_code() -> None:
    """Salah ketik satu kode (mis. "JA" untuk Jepang) diam-diam menjatuhkan artikelnya ke Global."""
    iso = {c.alpha_2 for c in pycountry.countries}
    assert iso >= APAC_COUNTRY_CODES
    assert all(code == code.upper() and len(code) == 2 for code in APAC_COUNTRY_CODES)


def test_covers_the_countries_the_team_cares_about() -> None:
    for code in ("ID", "SG", "MY", "JP", "KR", "CN", "TW", "IN", "AU", "NZ", "PH", "VN", "TH"):
        assert code in APAC_COUNTRY_CODES


def test_leaves_out_other_regions() -> None:
    """Asia Tengah, Timur Tengah, Rusia, dan Barat tidak termasuk (lihat docstring modul)."""
    for code in ("US", "GB", "DE", "FR", "RU", "KZ", "UZ", "SA", "AE", "IL", "BR", "ZA"):
        assert code not in APAC_COUNTRY_CODES
