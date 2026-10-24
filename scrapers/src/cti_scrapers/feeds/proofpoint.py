"""Proofpoint Threat Insight -- selector diganti ke pola href (census staging 2026-10-01, Fase 10.D). Artikel di `/us/blog/threat-insight/<slug>`. (Feed `rss.xml` situsnya = press release, BUKAN threat insight, jadi gak dipakai.)

XPath absolut lama gak match lagi. Sekarang `link_card_xpaths` (lihat `_links.py`) -- yang dipegang
cuma pola href artikel, bukan posisi div ke-N. `wait_for`: halaman dirender di klien, tanpa menunggu
anchor artikel muncul `page.content()` ambil HTML sebelum daftar ada."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread

from cti_scrapers.feeds._links import link_card_xpaths

_TITLE, _LINK = link_card_xpaths("contains(@href, '/us/blog/threat-insight/')")


class Proofpoint(XPathScraper):
    meta = ScraperMeta(
        id="proofpoint",
        content_kind="vendor_research",
        source="Proofpoint",
        schedule=spread("0 * * * *", "proofpoint"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=6,
        tags=("migrated",),
        legacy_label="NEW THREAT INSIGHT ARTICLE FROM PROOFPOINT",
        legacy_script="proofpointThreat",
    )
    url = "https://www.proofpoint.com/us/blog/threat-insight"
    base_url = "https://www.proofpoint.com"
    indexed = False
    wait_for = "a[href*='/us/blog/threat-insight/']"
    title_xpath = _TITLE
    link_xpath = _LINK
