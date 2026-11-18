"""Munit -- hasil migrasi otomatis dari `ScraperNews/munitThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from datetime import date

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Munit(RSSScraper):
    meta = ScraperMeta(
        id="munit",
        added=date(2026, 4, 28),
        content_kind="vendor_research",
        source="Munit",
        schedule=spread("45 * * * *", "munit"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM MUNIT",
        legacy_script="munitThreat",
    )
    feeds = ("https://munit.io/feed/",)
