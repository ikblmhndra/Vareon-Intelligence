"""Ecrimech -- hasil migrasi otomatis dari `ScraperNews/ecrimeThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Ecrime(RSSScraper):
    meta = ScraperMeta(
        id="ecrime",
        source="Ecrimech",
        schedule=spread("31 * * * *", "ecrime"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM ECRIMECH",
        legacy_script="ecrimeThreat",
    )
    feeds = ("https://ecrime.ch/app/intel-news.php?rss",)
