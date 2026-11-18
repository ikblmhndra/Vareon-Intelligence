"""Advisory PyPI -- gantiin `techstackLibrary/techstackPYPI.py`. Lihat
`cti_scraper.families.library_advisories` buat alur dan daftar bug lama."""

from __future__ import annotations

from datetime import date

from cti_scraper.base import ScraperMeta
from cti_scraper.families.library_advisories import LibraryAdvisoryScraper


class TechstackPypi(LibraryAdvisoryScraper):
    meta = ScraperMeta(
        id="techstack_pypi",
        added=date(2026, 9, 30),
        content_kind="advisory",
        source="TechStack PyPI Advisory",
        source_url="https://osv.dev/list?ecosystem=PyPI",
        schedule="48 * * * *",
        rate_limit="300/minute",
        max_items=15,
        tags=("migrated", "bespoke", "advisory"),
        legacy_script="techstackPYPI",
    )
    ecosystem = "pypi"
    label = "PYPI"
    packages = ("requests", "selenium", "pandas")
