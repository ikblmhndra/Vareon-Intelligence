"""Unit42 -- hasil migrasi otomatis dari `ScraperNews/unit42Threat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Unit42(RSSScraper):
    meta = ScraperMeta(
        id="unit42",
        source="Unit42",
        schedule=spread("31 * * * *", "unit42"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM UNIT42",
        legacy_script="unit42Threat",
    )
    feeds = ("https://unit42.paloaltonetworks.com/feed/",)
