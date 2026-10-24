"""Rhino Security -- hasil migrasi otomatis dari `ScraperNews/rhinosecThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Rhinosec(RSSScraper):
    meta = ScraperMeta(
        id="rhinosec",
        source="Rhino Security",
        schedule=spread("31 * * * *", "rhinosec"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM RHINO SECURITY",
        legacy_script="rhinosecThreat",
    )
    feeds = ("https://rhinosecuritylabs.com/feed/",)
