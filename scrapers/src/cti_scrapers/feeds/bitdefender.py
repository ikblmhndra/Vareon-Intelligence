"""Bitdefender Labs -- referensi family RSS. Bandingkan sama
`ScraperNews/bitdefenderThreat.py` asli (33 baris): UA header, cabang
status-code, loop is_new_and_mark/push_job -- semua itu boilerplate yang
di sini jadi default framework.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Bitdefender(RSSScraper):
    meta = ScraperMeta(
        id="bitdefender",
        content_kind="vendor_research",
        source="Bitdefender Labs",
        schedule=spread("*/15 * * * *", "bitdefender"),
        tags=("vendor",),
        legacy_label="NEW ARTICLE FROM BITDEFENDER",
        legacy_script="bitdefenderThreat",
    )
    feeds = ("https://www.bitdefender.com/nuxt/api/en-us/rss/labs/",)

    # Scraper lama nulis `datetime.now().date()` sbg posted_on -- gak pernah
    # parse pubDate RSS sama sekali. Sengaja dipertahankan biar golden test
    # cocok sama fixture Fase 0; date_path=None artinya RSSScraper juga
    # pakai waktu-scrape, bukan tanggal artikel asli. Migrasi berikutnya yang
    # gak butuh cocok fixture lama boleh pakai default (date_path="pubDate").
