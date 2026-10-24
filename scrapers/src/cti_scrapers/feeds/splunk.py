"""Splunk -- selector diganti ke pola href (census staging 2026-10-01, Fase 10.D). Artikel di `/en_us/blog/security/<slug>`.

XPath absolut lama gak match lagi. Sekarang `link_card_xpaths` (lihat `_links.py`) -- yang dipegang
cuma pola href artikel, bukan posisi div ke-N. `wait_for`: halaman dirender di klien, tanpa menunggu
anchor artikel muncul `page.content()` ambil HTML sebelum daftar ada."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread

from cti_scrapers.feeds._links import link_card_xpaths

_TITLE, _LINK = link_card_xpaths("contains(@href, '/en_us/blog/security/')")


class Splunk(XPathScraper):
    meta = ScraperMeta(
        id="splunk",
        content_kind="vendor_research",
        source="Splunk",
        schedule=spread("45 * * * *", "splunk"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=6,
        tags=("migrated",),
        legacy_label="NEW RECENT ARTICLE FROM SPLUNK",
        legacy_script="splunkThreat",
    )
    url = "https://www.splunk.com/en_us/blog/security.html"
    base_url = "https://www.splunk.com"
    indexed = False
    wait_for = "a[href*='/en_us/blog/security/']"
    title_xpath = _TITLE
    link_xpath = _LINK
