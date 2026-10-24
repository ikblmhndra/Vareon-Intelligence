"""Elastic Labs -- hasil migrasi otomatis dari `ScraperNews/elasticLabThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class ElasticLab(RSSScraper):
    meta = ScraperMeta(
        id="elastic_lab",
        content_kind="vendor_research",
        source="Elastic Labs",
        schedule=spread("30 * * * *", "elastic_lab"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM ELASTIC LABS",
        legacy_script="elasticLabThreat",
    )
    feeds = ("https://www.elastic.co/security-labs/rss/feed.xml",)
    html_unescape = True  # feed lama pakai html.unescape() sebelum parse XML
