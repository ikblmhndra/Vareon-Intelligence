"""Artic Wolf -- hasil migrasi otomatis dari `ScraperNews/articThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Artic(RSSScraper):
    meta = ScraperMeta(
        id="artic",
        source="Artic Wolf",
        schedule=spread("46 * * * *", "artic"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM ARTIC WOLF",
        legacy_script="articThreat",
    )
    feeds = (
        "https://arcticwolf.com/resources/category/report/feed/",
        "https://arcticwolf.com/resources/tag/cyberattacks-breaches/feed/",
    )
