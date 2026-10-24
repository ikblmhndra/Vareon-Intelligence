"""Securelist -- hasil migrasi otomatis dari `ScraperNews/securelistThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Securelist(RSSScraper):
    meta = ScraperMeta(
        id="securelist",
        source="Securelist",
        schedule=spread("0 * * * *", "securelist"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM SECURELIST",
        legacy_script="securelistThreat",
    )
    feeds = ("https://securelist.com/feed/",)
