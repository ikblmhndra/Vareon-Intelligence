"""Asec Ahn Lab -- hasil migrasi otomatis dari `ScraperNews/asecAhnThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class AsecAhn(RSSScraper):
    meta = ScraperMeta(
        id="asec_ahn",
        content_kind="vendor_research",
        source="Asec Ahn Lab",
        schedule=spread("30 * * * *", "asec_ahn"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM ASEC AHN LAB",
        legacy_script="asecAhnThreat",
    )
    feeds = ("https://asec.ahnlab.com/en/feed/",)
