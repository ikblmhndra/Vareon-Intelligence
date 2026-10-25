"""Depi (dulu L&H / landh.tech) -- diganti ke RSS (census staging 2026-10-01, Fase 10.D). Perusahaannya
rebrand: `landh.tech/blog/` sekarang menampilkan halaman "Depi" dan XPath absolut lama gak match.
Blog yang aktif ada di `depi.security`, dengan feed RSS resmi (diiklankan lewat
`<link rel="alternate">`, 19 post riset keamanan). URL artikel lama (`landh.tech/...`) beda host dari
artikel baru -- gak ada tumpang-tindih dedup, artikel lama gak bakal ke-alert ulang."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Landth(RSSScraper):
    meta = ScraperMeta(
        id="landth",
        content_kind="vendor_research",
        source="Depi (dulu L&H)",
        schedule=spread("16 * * * *", "landth"),
        tags=("migrated",),
        legacy_label="NEW RECENT ARTICLE FROM LANDTH",
        legacy_script="landthThreat",
    )
    feeds = ("https://depi.security/rss.xml",)
