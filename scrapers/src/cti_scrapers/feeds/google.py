"""Google Threat Group -- hasil migrasi otomatis dari `ScraperNews/googleThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.

**WAIVER 2026-10-01 (census staging, Fase 10.D) -- `enabled=False`.** Feed TAG (`blog.google/threat-analysis-group/rss/`) sekarang 404. Satu-satunya pengganti yang hidup (`blog.google/rss/`) itu feed SELURUH blog Google (isinya mis. "Google's AI ranks #1 for predicting flu hospitalizations"), bukan threat analysis. Konten threat-intelligence Google sudah dipantau scraper `google_cloud` (cloudblog.withgoogle.com/topics/threat-intelligence) dan `mandiant`.
Diaktifkan lagi kalau sumbernya balik/ada jalur baru -- lihat `docs/KNOWN_BROKEN.md`.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Google(RSSScraper):
    meta = ScraperMeta(
        id="google",
        source="Google Threat Group",
        schedule=spread("30 * * * *", "google"),
        enabled=False,  # waiver 10.D, lihat docstring
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM GOOGLE THREAT GROUP",
        legacy_script="googleThreat",
    )
    feeds = ("https://blog.google/threat-analysis-group/rss/",)
    xml_fixups = (
        ("&ndash;", ""),
        ("&", "&amp;"),
    )
    html_unescape = True  # feed lama pakai html.unescape() sebelum parse XML
