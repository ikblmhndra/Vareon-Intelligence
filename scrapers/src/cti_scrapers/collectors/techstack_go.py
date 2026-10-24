"""Advisory Go -- gantiin `techstackLibrary/techstackGO.py`. Lihat
`cti_scraper.families.library_advisories` buat alur dan daftar bug lama."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.library_advisories import LibraryAdvisoryScraper


class TechstackGo(LibraryAdvisoryScraper):
    meta = ScraperMeta(
        id="techstack_go",
        content_kind="advisory",
        source="TechStack Golang Advisory",
        schedule="50 * * * *",
        rate_limit="300/minute",
        max_items=15,
        tags=("migrated", "bespoke", "advisory"),
        legacy_script="techstackGO",
    )
    ecosystem = "go"
    label = "GOLANG"
    packages = ("github.com/docker/docker", "github.com/opencontainers/runc")
