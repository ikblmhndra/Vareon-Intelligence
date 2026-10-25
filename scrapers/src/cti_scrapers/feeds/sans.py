"""SANS -- selector diganti ke pola href (census staging 2026-10-01, Fase 10.D). Filter `?focus-area=...` lama sudah gak dipakai (redirect ke `/white-papers`); artikel di `/white-papers/<slug>`. Scope: SEMUA white paper, bukan cuma focus-area yang dulu dipilih.

XPath absolut lama gak match lagi. Sekarang `link_card_xpaths` (lihat `_links.py`) -- yang dipegang
cuma pola href artikel, bukan posisi div ke-N. `wait_for`: halaman dirender di klien, tanpa menunggu
anchor artikel muncul `page.content()` ambil HTML sebelum daftar ada."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread

from cti_scrapers.feeds._links import link_card_xpaths

_TITLE, _LINK = link_card_xpaths("contains(@href, '/white-papers/')")


class Sans(XPathScraper):
    meta = ScraperMeta(
        id="sans",
        content_kind="vendor_research",
        source="Sans",
        schedule=spread("30 * * * *", "sans"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=6,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM SANS",
        legacy_script="sansThreat",
    )
    url = "https://www.sans.org/white-papers"
    base_url = "https://www.sans.org"
    indexed = False
    wait_for = "a[href*='/white-papers/']"
    title_xpath = _TITLE
    link_xpath = _LINK
