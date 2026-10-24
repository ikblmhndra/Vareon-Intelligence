"""Infostealer -- hasil migrasi otomatis dari `ScraperNews/infostealerThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Infostealer(RSSScraper):
    meta = ScraperMeta(
        id="infostealer",
        source="Infostealer",
        schedule=spread("46 * * * *", "infostealer"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM INFOSTEALER",
        legacy_script="infostealerThreat",
    )
    feeds = ("https://www.infostealers.com/learn-info-stealers/feed/",)
