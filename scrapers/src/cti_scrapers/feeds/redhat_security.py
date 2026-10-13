from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class RedHatSecurity(RSSScraper):
    meta = ScraperMeta(
        id="redhat_security",
        source="redhat.com",
        schedule=spread("*/15 * * * *", "redhat_security"),
        tags=("Red Hat Security Blog",),
        legacy_label="Red Hat Security Blog",
        legacy_script="redhat_security",
    )
    feeds = ("https://www.redhat.com/en/rss/blog/channel/security",)

    # Scraper lama nulis `datetime.now().date()` sbg posted_on -- gak pernah
    # parse pubDate RSS sama sekali. Sengaja dipertahankan biar golden test
    # cocok sama fixture Fase 0; date_path=None artinya RSSScraper juga
    # pakai waktu-scrape, bukan tanggal artikel asli. Migrasi berikutnya yang
    # gak butuh cocok fixture lama boleh pakai default (date_path="pubDate").
    date_path = None
