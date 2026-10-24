"""Fortinet -- hasil migrasi otomatis dari `ScraperNews/fortinetThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Fortinet(RSSScraper):
    meta = ScraperMeta(
        id="fortinet",
        content_kind="vendor_research",
        source="Fortinet",
        schedule=spread("45 * * * *", "fortinet"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM FORTINET",
        legacy_script="fortinetThreat",
    )
    feeds = (
        "https://feeds.fortinet.com/fortinet/blog/psirt",
        "https://feeds.fortinet.com/fortinet/blogs",
    )
