"""Team Cymru -- diganti ke RSS (census staging 2026-10-01, Fase 10.D). Halaman
`/categories/threat-research` sekarang 404 (situs pindah ke koleksi Webflow `post`), jadi XPath absolut
lama gak punya apa-apa buat dicocokkan. Feed koleksi itu: `/post/rss.xml`. Scope = SEMUA post blog,
bukan cuma kategori threat-research (feed-nya gak dipecah per kategori)."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Cymru(RSSScraper):
    meta = ScraperMeta(
        id="cymru",
        content_kind="vendor_research",
        source="Cymru",
        schedule=spread("47 * * * *", "cymru"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM CYMRU",
        legacy_script="cymruThreat",
    )
    feeds = ("https://www.team-cymru.com/post/rss.xml",)
