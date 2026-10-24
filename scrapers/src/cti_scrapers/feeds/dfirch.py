"""Dfirch -- hasil migrasi otomatis dari `ScraperNews/dfirchThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Dfirch(RSSScraper):
    meta = ScraperMeta(
        id="dfirch",
        content_kind="vendor_research",
        source="Dfirch",
        schedule=spread("33 * * * *", "dfirch"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM DFIRCH",
        legacy_script="dfirchThreat",
    )
    feeds = ("https://dfir.ch/posts/index.xml",)
