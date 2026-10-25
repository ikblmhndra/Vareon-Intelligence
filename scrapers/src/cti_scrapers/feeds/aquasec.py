"""Aquasec -- diganti ke RSS (census staging 2026-10-01, Fase 10.D). XPath absolut lama
(`.../div[{i}]/a/div[1]/...`) sudah gak match apa pun setelah situs di-redesign, dan situsnya gak
mengiklankan feed lewat `<link rel="alternate">` -- URL feed WordPress-nya ketemu dari probe path umum.
`/feed/` memuat 10 post terbaru, scope sama dengan halaman `/blog/` yang dulu di-scrape."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Aquasec(RSSScraper):
    meta = ScraperMeta(
        id="aquasec",
        content_kind="vendor_research",
        source="Aquasec",
        schedule=spread("45 * * * *", "aquasec"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM AQUASEC",
        legacy_script="aquasecThreat",
    )
    feeds = ("https://www.aquasec.com/feed/",)
