"""Threatmon -- hasil migrasi otomatis dari `ScraperNews/threatmonThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Threatmon(RSSScraper):
    meta = ScraperMeta(
        id="threatmon",
        content_kind="vendor_research",
        source="Threatmon",
        schedule=spread("16 * * * *", "threatmon"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM THREATMON",
        legacy_script="threatmonThreat",
    )
    feeds = ("https://threatmon.io/feed/",)
    xml_fixups = (
        ("&ndash;", ""),
        ("&", "&amp;"),
    )
    html_unescape = True  # feed lama pakai html.unescape() sebelum parse XML
