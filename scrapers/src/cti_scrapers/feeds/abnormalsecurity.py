"""Abnormal Security -- selector diganti ke pola href (census staging 2026-10-01, Fase 10.D). Halaman kategori lama (`/blog/category/threat-intel`) sekarang `/blog?filter=threat-intel`; artikel di `/blog/<slug>`.

XPath absolut lama gak match lagi. Sekarang `link_card_xpaths` (lihat `_links.py`) -- yang dipegang
cuma pola href artikel, bukan posisi div ke-N. `wait_for` dibatasi ke `main`: `wait_for_selector` nunggu elemen PERTAMA yang cocok jadi visible, dan di luar `main` ada link `/blog/` di menu yang tersembunyi (timeout 30 dtk kalau gak dibatasi). `wait_for`: halaman dirender di klien, tanpa menunggu
anchor artikel muncul `page.content()` ambil HTML sebelum daftar ada."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread

from cti_scrapers.feeds._links import link_card_xpaths

_TITLE, _LINK = link_card_xpaths(
    "starts-with(@href, '/blog/') or starts-with(@href, 'https://abnormal.ai/blog/')"
)


class Abnormalsecurity(XPathScraper):
    meta = ScraperMeta(
        id="abnormalsecurity",
        content_kind="vendor_research",
        source="Abnormal Security",
        schedule=spread("15 * * * *", "abnormalsecurity"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=6,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM ABNORMAL SECURITY",
        legacy_script="abnormalsecurityThreat",
    )
    url = "https://abnormal.ai/blog?filter=threat-intel"
    base_url = "https://abnormal.ai"
    indexed = False
    wait_for = "main a[href^='/blog/']"
    title_xpath = _TITLE
    link_xpath = _LINK
