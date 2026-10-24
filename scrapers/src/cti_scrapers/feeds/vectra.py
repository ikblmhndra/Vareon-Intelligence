"""Vectra -- hasil migrasi otomatis dari `ScraperNews/vectraThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Vectra(RSSScraper):
    meta = ScraperMeta(
        id="vectra",
        content_kind="vendor_research",
        source="Vectra",
        schedule=spread("45 * * * *", "vectra"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM VECTRA",
        legacy_script="vectraThreat",
    )
    feeds = ("https://www.vectra.ai/blog/rss.xml",)
