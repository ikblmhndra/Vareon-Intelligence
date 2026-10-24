"""Dark Reading -- hasil migrasi otomatis dari `ScraperNews/darkreadingThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Darkreading(RSSScraper):
    meta = ScraperMeta(
        id="darkreading",
        source="Dark Reading",
        schedule=spread("30 * * * *", "darkreading"),
        tags=("migrated",),
        legacy_label="NEW RECENT ARTICLE FROM DARK READING",
        legacy_script="darkreadingThreat",
    )
    feeds = ("https://www.darkreading.com/rss.xml",)
    xml_fixups = (
        ("&ndash;", ""),
        ("&", "&amp;"),
    )
    html_unescape = True  # feed lama pakai html.unescape() sebelum parse XML
