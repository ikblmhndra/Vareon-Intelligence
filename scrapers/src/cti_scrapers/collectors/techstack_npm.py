"""Advisory NPM -- gantiin `techstackLibrary/techstackNPM.py`. Lihat
`cti_scraper.families.library_advisories` buat alur dan daftar bug lama."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.library_advisories import LibraryAdvisoryScraper


class TechstackNpm(LibraryAdvisoryScraper):
    meta = ScraperMeta(
        id="techstack_npm",
        content_kind="advisory",
        source="TechStack NPM Advisory",
        schedule="46 * * * *",
        rate_limit="300/minute",
        max_items=15,
        tags=("migrated", "bespoke", "advisory"),
        legacy_script="techstackNPM",
    )
    ecosystem = "npm"
    label = "NPM"
    packages = ("lodash", "debug", "request")
