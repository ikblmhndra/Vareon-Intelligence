from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class CloudVulnDB(RSSScraper):
    meta = ScraperMeta(
        id="cloud_vuln_db",
        source="cloudvulndb.org",
        schedule=spread("*/15 * * * *", "cloud_vuln_db"),
        tags=("vendor",),
        legacy_label="Cloud Vulnerability Database",
        legacy_script="cloud_vuln_db",
    )
    feeds = ("https://www.cloudvulndb.org/rss/feed.xml",)

    # Scraper lama nulis `datetime.now().date()` sbg posted_on -- gak pernah
    # parse pubDate RSS sama sekali. Sengaja dipertahankan biar golden test
    # cocok sama fixture Fase 0; date_path=None artinya RSSScraper juga
    # pakai waktu-scrape, bukan tanggal artikel asli. Migrasi berikutnya yang
    # gak butuh cocok fixture lama boleh pakai default (date_path="pubDate").
    date_path = None
