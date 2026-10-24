"""Re Security -- hasil migrasi otomatis dari `ScraperNews/resecurityThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Resecurity(RSSScraper):
    meta = ScraperMeta(
        id="resecurity",
        source="Re Security",
        schedule=spread("32 * * * *", "resecurity"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM RE SECURITY",
        legacy_script="resecurityThreat",
    )
    feeds = ("https://www.resecurity.com/feed",)
