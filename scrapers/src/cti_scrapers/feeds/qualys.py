"""Qualys Security -- hasil migrasi otomatis dari `ScraperNews/qualysThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Qualys(RSSScraper):
    meta = ScraperMeta(
        id="qualys",
        source="Qualys Security",
        schedule=spread("46 * * * *", "qualys"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM QUALYS SECURITY",
        legacy_script="qualysThreat",
    )
    feeds = ("https://blog.qualys.com/vulnerabilities-threat-research/feed",)
