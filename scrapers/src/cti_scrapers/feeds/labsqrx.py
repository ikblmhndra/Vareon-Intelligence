"""Labs Sqrx -- hasil migrasi otomatis dari `ScraperNews/labsqrxThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Labsqrx(RSSScraper):
    meta = ScraperMeta(
        id="labsqrx",
        content_kind="vendor_research",
        source="Labs Sqrx",
        schedule=spread("16 * * * *", "labsqrx"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM LABS SQRX",
        legacy_script="labsqrxThreat",
    )
    feeds = ("https://labs.sqrx.com/feed",)
    xml_fixups = (
        ("&ndash;", ""),
        ("&", "&amp;"),
    )
    html_unescape = True  # feed lama pakai html.unescape() sebelum parse XML
