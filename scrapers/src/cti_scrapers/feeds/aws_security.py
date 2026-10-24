from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Awssecurity(RSSScraper):
    meta = ScraperMeta(
        id="aws_security",
        content_kind="vendor_research",
        source="AWS Security",
        schedule=spread("*/15 * * * *", "awssecurity"),
        tags=("vendor",),
        legacy_label="NEW ARTICLE FROM AWS SECURITY BLOG",
        legacy_script="awssecurity",
    )
    feeds = ("https://aws.amazon.com/blogs/security/feed/",)

    # Scraper lama nulis `datetime.now().date()` sbg posted_on -- gak pernah
    # parse pubDate RSS sama sekali. Sengaja dipertahankan biar golden test
    # cocok sama fixture Fase 0; date_path=None artinya RSSScraper juga
    # pakai waktu-scrape, bukan tanggal artikel asli. Migrasi berikutnya yang
    # gak butuh cocok fixture lama boleh pakai default (date_path="pubDate").
