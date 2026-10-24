"""Google Cloud Ti -- hasil migrasi otomatis dari `ScraperNews/googleCloudThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class GoogleCloud(RSSScraper):
    meta = ScraperMeta(
        id="google_cloud",
        source="Google Cloud Ti",
        schedule=spread("31 * * * *", "google_cloud"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM GOOGLE CLOUD TI",
        legacy_script="googleCloudThreat",
    )
    feeds = ("https://cloudblog.withgoogle.com/topics/threat-intelligence/rss/",)
