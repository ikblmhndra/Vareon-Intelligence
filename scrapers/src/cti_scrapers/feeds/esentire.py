"""Esentire -- hasil migrasi otomatis dari `ScraperNews/esentireThreat.py`
(codemod Fase 4, family XPath runtime="browser"). Cek
`migration_report.json` buat detail ekstraksi. WAJIB lewat `dry-run` +
`verify` sebelum `enable` -- lihat docs/ADDING_A_SCRAPER.md.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread


class Esentire(XPathScraper):
    meta = ScraperMeta(
        id="esentire",
        content_kind="vendor_research",
        source="Esentire",
        schedule=spread("32 * * * *", "esentire"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=4,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM ESENTIRE",
        legacy_script="esentireThreat",
    )
    url = "https://www.esentire.com/resources/blog?blogType%5B%5D=Threat%20Intelligence"
    title_xpath = "/html/body/section[2]/div[2]/div/a[{i}]/div/h3"
    link_xpath = "/html/body/section[2]/div[2]/div/a[{i}]"
