"""Prodaft -- selector diganti ke pola href (census staging 2026-10-01, Fase 10.D). Host kanonik `www.prodaft.com`; artikel di `/blog/<slug>` (halaman daftarnya `/blogs`).

XPath absolut lama gak match lagi. Sekarang `link_card_xpaths` (lihat `_links.py`) -- yang dipegang
cuma pola href artikel, bukan posisi div ke-N. `wait_for`: halaman dirender di klien, tanpa menunggu
anchor artikel muncul `page.content()` ambil HTML sebelum daftar ada."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread

from cti_scrapers.feeds._links import link_card_xpaths

_TITLE, _LINK = link_card_xpaths("starts-with(@href, '/blog/')")


class Prodraft(XPathScraper):
    meta = ScraperMeta(
        id="prodraft",
        content_kind="vendor_research",
        source="Prodaft",
        schedule=spread("45 * * * *", "prodraft"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=6,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM PRODAFT",
        legacy_script="prodraftThreat",
    )
    url = "https://www.prodaft.com/blogs"
    base_url = "https://www.prodaft.com"
    indexed = False
    wait_for = "a[href^='/blog/']"
    title_xpath = _TITLE
    link_xpath = _LINK
