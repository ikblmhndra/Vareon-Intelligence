"""K7 Security -- diganti ke RSS (census staging 2026-10-01, Fase 10.D). Blog pindah dari
`www.k7computing.com/in/blog` (sekarang cuma halaman pengantar) ke subdomain WordPress
`blog.k7computing.com`, yang punya feed RSS resmi (10 post terbaru). XPath absolut lama gak punya apa-apa
buat dicocokkan di halaman itu lagi."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class K7security(RSSScraper):
    meta = ScraperMeta(
        id="k7security",
        content_kind="vendor_research",
        source="K7 Security",
        schedule=spread("1 * * * *", "k7security"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM K7 SECURITY",
        legacy_script="k7securityThreat",
    )
    feeds = ("https://blog.k7computing.com/feed/",)
