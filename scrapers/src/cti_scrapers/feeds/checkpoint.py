"""Checkpoint Research -- hasil migrasi otomatis dari `ScraperNews/checkpointThreat.py`
(codemod Fase 4, family XPath runtime="browser"). Cek
`migration_report.json` buat detail ekstraksi. WAJIB lewat `dry-run` +
`verify` sebelum `enable` -- lihat docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread


class Checkpoint(XPathScraper):
    meta = ScraperMeta(
        id="checkpoint",
        content_kind="vendor_research",
        source="Checkpoint Research",
        schedule=spread("30 * * * *", "checkpoint"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=4,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM CHECKPOINT RESEARCH",
        legacy_script="checkpointThreat",
    )
    url = "https://research.checkpoint.com/latest-publications/"
    title_xpath = "/html/body/section/div/div[2]/div[1]/div[1]/div[{i}]/div/div[2]/h3/a/text()"
    link_xpath = "/html/body/section/div/div[2]/div[1]/div[1]/div[{i}]/div/div[2]/h3/a/@href"
