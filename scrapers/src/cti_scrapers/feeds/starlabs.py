"""Starlabs -- hasil migrasi otomatis dari `ScraperNews/starlabsThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Starlabs(RSSScraper):
    meta = ScraperMeta(
        id="starlabs",
        content_kind="vendor_research",
        source="Starlabs",
        schedule=spread("32 * * * *", "starlabs"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM STARLABS",
        legacy_script="starlabsThreat",
    )
    feeds = ("https://starlabs.sg/blog/index.xml",)
