"""Hunt.io -- selector diganti ke pola href (census staging 2026-10-01, Fase 10.D). Situs Framer; artikel di `./blog/<slug>` (href relatif berawalan `./`).

XPath absolut lama gak match lagi. Sekarang `link_card_xpaths` (lihat `_links.py`) -- yang dipegang
cuma pola href artikel, bukan posisi div ke-N. `wait_for`: halaman dirender di klien, tanpa menunggu
anchor artikel muncul `page.content()` ambil HTML sebelum daftar ada."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread

from cti_scrapers.feeds._links import link_card_xpaths

_TITLE, _LINK = link_card_xpaths("contains(@href, '/blog/')")


class Huntio(XPathScraper):
    meta = ScraperMeta(
        id="huntio",
        content_kind="vendor_research",
        source="Hunt Io",
        schedule=spread("16 * * * *", "huntio"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=6,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM HUNT IO",
        legacy_script="huntioThreat",
    )
    url = "https://hunt.io/blog"
    base_url = "https://hunt.io"
    indexed = False
    wait_for = "a[href*='/blog/']"
    title_xpath = _TITLE
    link_xpath = _LINK
