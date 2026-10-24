"""Dfir Report -- hasil migrasi otomatis dari `ScraperNews/dfirThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Dfir(RSSScraper):
    meta = ScraperMeta(
        id="dfir",
        source="Dfir Report",
        schedule=spread("1 * * * *", "dfir"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM DFIR REPORT",
        legacy_script="dfirThreat",
    )
    feeds = ("https://thedfirreport.com/feed/",)
