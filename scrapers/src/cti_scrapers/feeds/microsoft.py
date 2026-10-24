"""Microsoft -- hasil migrasi otomatis dari `ScraperNews/microsoftThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Microsoft(RSSScraper):
    meta = ScraperMeta(
        id="microsoft",
        source="Microsoft",
        schedule=spread("32 * * * *", "microsoft"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM MICROSOFT",
        legacy_script="microsoftThreat",
    )
    feeds = ("https://www.microsoft.com/en-us/security/blog/topic/threat-intelligence/feed/",)
