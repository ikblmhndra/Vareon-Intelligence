"""Redcanary -- hasil migrasi otomatis dari `ScraperNews/redcanaryThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Redcanary(RSSScraper):
    meta = ScraperMeta(
        id="redcanary",
        source="Redcanary",
        schedule=spread("30 * * * *", "redcanary"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM REDCANARY",
        legacy_script="redcanaryThreat",
    )
    feeds = ("https://redcanary.com/blog/feed/",)
