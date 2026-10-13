from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class ZeroDayInitiative(RSSScraper):
    meta = ScraperMeta(
        id="zeroday_initiative",
        source="zerodayinitiative.com",
        schedule=spread("*/15 * * * *", "zeroday_initiative"),
        tags=("Zero Day Initiative",),
        legacy_label="Zero Day Initiative",
        legacy_script="zeroday_initiative",
    )
    feeds = ("https://www.zerodayinitiative.com/rss/upcoming/",)

    # Scraper lama nulis `datetime.now().date()` sbg posted_on -- gak pernah
    # parse pubDate RSS sama sekali. Sengaja dipertahankan biar golden test
    # cocok sama fixture Fase 0; date_path=None artinya RSSScraper juga
    # pakai waktu-scrape, bukan tanggal artikel asli. Migrasi berikutnya yang
    # gak butuh cocok fixture lama boleh pakai default (date_path="pubDate").
    date_path = None
