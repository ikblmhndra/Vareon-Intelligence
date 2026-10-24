"""Nquiringminds -- hasil migrasi otomatis dari `ScraperNews/nquiringMindsThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.

**WAIVER 2026-10-01 (census staging, Fase 10.D) -- `enabled=False`.** Feed lama (`nquiringminds.com/feed/`) 404. Feed baru (`nquiringminds.com/rss.xml`, 6 item) isinya postingan template/blog developer ("How to Use TSConfig Path Aliases", "Make Awesome Blog Posts People Will Love") -- bukan CTI sama sekali, jadi gak layak dipantau.
Diaktifkan lagi kalau sumbernya balik/ada jalur baru -- lihat `docs/KNOWN_BROKEN.md`.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class NquiringMinds(RSSScraper):
    meta = ScraperMeta(
        id="nquiring_minds",
        content_kind="vendor_research",
        source="Nquiringminds",
        schedule=spread("16 * * * *", "nquiring_minds"),
        enabled=False,  # waiver 10.D, lihat docstring
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM NQUIRINGMINDS",
        legacy_script="nquiringMindsThreat",
    )
    feeds = ("https://nquiringminds.com/feed/",)
