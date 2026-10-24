"""Recordedfuture -- hasil migrasi otomatis dari `ScraperNews/recordedFutureThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class RecordedFuture(RSSScraper):
    meta = ScraperMeta(
        id="recorded_future",
        source="Recordedfuture",
        schedule=spread("30 * * * *", "recorded_future"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM RECORDEDFUTURE",
        legacy_script="recordedFutureThreat",
    )
    feeds = ("https://www.recordedfuture.com/feed/research",)
