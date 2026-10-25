"""BlackBerry -- hasil migrasi otomatis dari `ScraperNews/blackberryThreat.py`
(codemod Fase 4, family XPath runtime="browser"). Cek
`migration_report.json` buat detail ekstraksi. WAJIB lewat `dry-run` +
`verify` sebelum `enable` -- lihat docs/ADDING_A_SCRAPER.md.

**WAIVER 2026-10-01 (census staging, Fase 10.D) -- `enabled=False`.** URL lama (`blogs.blackberry.com/en/category/research-and-intelligence`) sekarang redirect ke `www.blackberry.com/en/secure-communications/insights/blog` -- isinya blog komunikasi aman (marketing: "Sovereign Communications Procurement", dst), BUKAN riset/intelijen ancaman. Gak ada feed RSS. Gak ada yang bisa dipantau di sini lagi.
Diaktifkan lagi kalau sumbernya balik/ada jalur baru -- lihat `docs/KNOWN_BROKEN.md`.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread


class Blackberry(XPathScraper):
    meta = ScraperMeta(
        id="blackberry",
        content_kind="vendor_research",
        source="BlackBerry",
        schedule=spread("0 * * * *", "blackberry"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=4,
        enabled=False,  # waiver 10.D, lihat docstring
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM NAME",
        legacy_script="blackberryThreat",
    )
    url = "https://blogs.blackberry.com/en/category/research-and-intelligence"
    title_xpath = (
        "/html/body/main/div[2]/section/div/div[2]/div[1]/div[{i}]/div/div/div/a[2]/text()"
    )
    link_xpath = "/html/body/main/div[2]/section/div/div[2]/div[1]/div[{i}]/div/div/div/a[2]/@href"
