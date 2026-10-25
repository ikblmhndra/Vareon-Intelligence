"""Advisory PyPI -- gantiin `techstackLibrary/techstackPYPI.py`. Lihat
`cti_scraper.families.library_advisories` buat alur dan daftar bug lama."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.library_advisories import LibraryAdvisoryScraper


class TechstackPypi(LibraryAdvisoryScraper):
    meta = ScraperMeta(
        id="techstack_pypi",
        content_kind="advisory",
        source="TechStack PyPI Advisory",
        schedule="48 * * * *",
        rate_limit="300/minute",
        max_items=15,
        tags=("migrated", "bespoke", "advisory"),
        legacy_script="techstackPYPI",
    )
    ecosystem = "pypi"
    label = "PYPI"
    packages = ("requests", "selenium", "pandas")
