"""Dragos -- selector diganti ke pola href (census staging 2026-10-01, Fase 10.D). Artikel di `/blog/<slug>`. Filter topik di query string URL dipertahankan; feed `blog.rss` mereka balikin 0 byte jadi gak dipakai.

XPath absolut lama gak match lagi. Sekarang `link_card_xpaths` (lihat `_links.py`) -- yang dipegang
cuma pola href artikel, bukan posisi div ke-N. `wait_for`: halaman dirender di klien, tanpa menunggu
anchor artikel muncul `page.content()` ambil HTML sebelum daftar ada."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread

from cti_scrapers.feeds._links import link_card_xpaths

_TITLE, _LINK = link_card_xpaths("contains(@href, '/blog/')")


class Dragos(XPathScraper):
    meta = ScraperMeta(
        id="dragos",
        content_kind="vendor_research",
        source="Dragos",
        schedule=spread("1 * * * *", "dragos"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=6,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM DRAGOS",
        legacy_script="dragosThreat",
    )
    url = "https://www.dragos.com/blog/?_block_blog_posts_topics=compliance%2Cransomware%2Cresearch%2Cthreats%2Cyear-in-review"
    base_url = "https://www.dragos.com"
    indexed = False
    wait_for = "a[href*='/blog/']"
    title_xpath = _TITLE
    link_xpath = _LINK
