"""Volexity -- hasil migrasi otomatis dari `ScraperNews/volexityThreat.py`
(codemod Fase 4, family XPath runtime="browser"). Cek
`migration_report.json` buat detail ekstraksi. WAJIB lewat `dry-run` +
`verify` sebelum `enable` -- lihat docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread


class Volexity(XPathScraper):
    meta = ScraperMeta(
        id="volexity",
        content_kind="vendor_research",
        source="Volexity",
        schedule=spread("1 * * * *", "volexity"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=4,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM VOLEXITY",
        legacy_script="volexityThreat",
    )
    url = "https://www.volexity.com/blog/"
    title_xpath = "/html/body/main/section[2]/div/div[2]/div[1]/article[{i}]/div/div[1]/a[1]/text()"
    link_xpath = "/html/body/main/section[2]/div/div[2]/div[1]/article[{i}]/div/div[1]/a[1]/@href"
