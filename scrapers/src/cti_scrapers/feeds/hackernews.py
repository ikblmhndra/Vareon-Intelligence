"""Hackernews -- hasil migrasi otomatis dari `ScraperNews/hackernewsThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Hackernews(RSSScraper):
    meta = ScraperMeta(
        id="hackernews",
        source="Hackernews",
        schedule=spread("30 * * * *", "hackernews"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM HACKERNEWS",
        legacy_script="hackernewsThreat",
    )
    feeds = ("https://feeds.feedburner.com/TheHackersNews",)
