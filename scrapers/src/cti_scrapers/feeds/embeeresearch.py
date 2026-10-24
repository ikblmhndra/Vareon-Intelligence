"""Embe Research -- hasil migrasi otomatis dari `ScraperNews/embeeresearchThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Embeeresearch(RSSScraper):
    meta = ScraperMeta(
        id="embeeresearch",
        content_kind="vendor_research",
        source="Embe Research",
        schedule=spread("16 * * * *", "embeeresearch"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM EMBE RESEARCH",
        legacy_script="embeeresearchThreat",
    )
    feeds = ("https://www.embeeresearch.io/rss/",)
    xml_fixups = (
        ("&ndash;", ""),
        ("&", "&amp;"),
    )
    html_unescape = True  # feed lama pakai html.unescape() sebelum parse XML
