"""Vmware -- hasil migrasi otomatis dari `ScraperNews/vmwareThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Vmware(RSSScraper):
    meta = ScraperMeta(
        id="vmware",
        content_kind="vendor_research",
        source="Vmware",
        schedule=spread("32 * * * *", "vmware"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM VMWARE",
        legacy_script="vmwareThreat",
    )
    feeds = ("https://blogs.vmware.com/security/feed",)
