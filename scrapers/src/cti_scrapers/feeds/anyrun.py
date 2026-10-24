"""Anyrun -- hasil migrasi otomatis dari `ScraperNews/anyrunThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Anyrun(RSSScraper):
    meta = ScraperMeta(
        id="anyrun",
        source="Anyrun",
        schedule=spread("31 * * * *", "anyrun"),
        tags=("migrated",),
        legacy_label="NEW MALWARE ANALYSIS ARTICLE FROM ANYRUN",
        legacy_script="anyrunThreat",
    )
    feeds = ("https://any.run/cybersecurity-blog/feed/",)
    xml_fixups = (
        ("&ndash;", ""),
        ("&", "&amp;"),
    )
    html_unescape = True  # feed lama pakai html.unescape() sebelum parse XML
