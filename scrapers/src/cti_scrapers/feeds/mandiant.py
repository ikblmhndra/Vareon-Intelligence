"""Mandiant Threat Intelligence -- rewrite item 4.8 (test case pertama,
2026-09-18). Gantiin `ScraperNews/stopped_script/mandiantThreat.py`, yang
`enabled=False` di Rundeck DAN isinya udah 100% ke-comment (upaya migrasi
Selenium->Playwright yang KETINGGALAN setengah jalan -- ada draft Playwright
di bawah komentar Selenium-nya, tapi berhenti di `print(...); exit()`
sebelum sempat nyambung ke `nlp_scan`).

**BUKAN scraper Selenium/Playwright sama sekali** -- draft lama nge-XPath
`mandiant.com/resources/blog` langsung, tapi situs itu SEKARANG REDIRECT ke
`cloud.google.com` (Mandiant diakuisisi & konten threat-intel-nya pindah ke
Google Cloud Blog "Threat Intelligence" topic pasca-akuisisi). Ketauan lewat
inspeksi browser langsung: halaman barunya nyediain **RSS feed resmi**
(`https://feeds.feedburner.com/threatintelligence/...`) -- jadi ini beres
lewat `RSSScraper` biasa, BUKAN `runtime="browser"`. Pola sama kayak scraper
migrasi Fase 4 lain: 3 baris deklaratif nutupin situs yang tadinya kepikir
butuh browser automation penuh.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Mandiant(RSSScraper):
    meta = ScraperMeta(
        id="mandiant",
        content_kind="vendor_research",
        source="Mandiant (Google Cloud Threat Intelligence)",
        schedule=spread("15 * * * *", "mandiant"),
        tags=("rewrite", "fase-4.8-test"),
        legacy_label="NEW ARTICLE FROM MANDIANT",
        legacy_script="mandiantThreat",
    )
    feeds = ("https://feeds.feedburner.com/threatintelligence/pvexyqv7v0v",)
