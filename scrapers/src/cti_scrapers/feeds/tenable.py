"""Tenable -- hasil migrasi otomatis dari `ScraperNews/tenableThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Tenable(RSSScraper):
    meta = ScraperMeta(
        id="tenable",
        source="Tenable",
        schedule=spread("45 * * * *", "tenable"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM TENABLE",
        legacy_script="tenableThreat",
    )
    feeds = ("https://feeds.feedburner.com/tenable/qaXL",)
