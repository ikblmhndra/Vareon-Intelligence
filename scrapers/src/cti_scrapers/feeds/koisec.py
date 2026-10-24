"""Koi Security -- hasil migrasi otomatis dari `ScraperNews/koisecThreat.py`
(codemod Fase 4, family XPath runtime="browser"). Cek
`migration_report.json` buat detail ekstraksi. WAJIB lewat `dry-run` +
`verify` sebelum `enable` -- lihat docs/ADDING_A_SCRAPER.md.

**WAIVER 2026-10-01 (census staging, Fase 10.D) -- `enabled=False`.** `koi.security` DAN `koi.ai` dua-duanya sekarang redirect ke halaman produk Palo Alto Networks (`paloaltonetworks.com/cortex/agentic-endpoint-security`) -- blog Koi sudah hilang.
Diaktifkan lagi kalau sumbernya balik/ada jalur baru -- lihat `docs/KNOWN_BROKEN.md`.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread


class Koisec(XPathScraper):
    meta = ScraperMeta(
        id="koisec",
        content_kind="vendor_research",
        source="Koi Security",
        schedule=spread("17 * * * *", "koisec"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=4,
        enabled=False,  # waiver 10.D, lihat docstring
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM KOI SECURITY",
        legacy_script="koisecThreat",
    )
    url = "https://www.koi.security/blog"
    title_xpath = (
        "/html/body/div/div[4]/main/section/div/div/div/div[3]/div/div[{i}]/div[1]/div[1]/h3"
    )
    link_xpath = "/html/body/div/div[4]/main/section/div/div/div/div[3]/div/div[{i}]/a"
    base_url = "https://www.koi.ai/blog"
