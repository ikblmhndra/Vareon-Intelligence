"""CIS Advisories -- selector diganti ke pola href (census staging 2026-10-01, Fase 10.D). Artikel di `/advisory/<slug>` (judul berformat `2026-105: ...`). Feed blog situsnya BUKAN advisory, jadi gak dipakai.

XPath absolut lama gak match lagi. Sekarang `link_card_xpaths` (lihat `_links.py`) -- yang dipegang
cuma pola href artikel, bukan posisi div ke-N. `wait_for`: halaman dirender di klien, tanpa menunggu
anchor artikel muncul `page.content()` ambil HTML sebelum daftar ada."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread

from cti_scrapers.feeds._links import link_card_xpaths

_TITLE, _LINK = link_card_xpaths("contains(@href, '/advisory/')")


class Cis(XPathScraper):
    meta = ScraperMeta(
        id="cis",
        content_kind="advisory",
        default_relevance="always",
        source="Cis",
        schedule=spread("30 * * * *", "cis"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=6,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM CIS",
        legacy_script="cisThreat",
    )
    url = "https://www.cisecurity.org/advisory"
    base_url = "https://www.cisecurity.org"
    indexed = False
    wait_for = "a[href*='/advisory/']"
    title_xpath = _TITLE
    link_xpath = _LINK
