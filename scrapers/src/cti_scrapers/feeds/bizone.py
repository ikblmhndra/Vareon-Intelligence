"""Bizone -- hasil migrasi otomatis dari `ScraperNews/bizoneThreat.py`
(codemod Fase 4, family XPath runtime="browser"). Cek
`migration_report.json` buat detail ekstraksi. WAJIB lewat `dry-run` +
`verify` sebelum `enable` -- lihat docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread


class Bizone(XPathScraper):
    meta = ScraperMeta(
        id="bizone",
        content_kind="vendor_research",
        source="Bizone",
        schedule=spread("0 * * * *", "bizone"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=4,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM BIZONE",
        legacy_script="bizoneThreat",
    )
    url = "https://bi.zone/eng/expertise/blog/"
    title_xpath = (
        "/html/body/div[1]/main/section[1]/div/div/div[3]/div/div/div[2]/div/div[{i}]/div/a/text()"
    )
    link_xpath = (
        "/html/body/div[1]/main/section[1]/div/div/div[3]/div/div/div[2]/div/div[{i}]/div/a/@href"
    )
    base_url = "https://bi.zone"
