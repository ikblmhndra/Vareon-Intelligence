"""Eset -- hasil migrasi otomatis dari `ScraperNews/esetThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Eset(RSSScraper):
    meta = ScraperMeta(
        id="eset",
        content_kind="vendor_research",
        source="Eset",
        schedule=spread("0 0/1 * * *", "eset"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM ESET",
        legacy_script="esetThreat",
    )
    feeds = ("https://www.welivesecurity.com/en/rss/feed/",)
    xml_fixups = (
        ("&ndash;", ""),
        ("&", "&amp;"),
    )
    html_unescape = True  # feed lama pakai html.unescape() sebelum parse XML
