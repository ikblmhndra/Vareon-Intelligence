"""Trustwave -- hasil migrasi otomatis dari `ScraperNews/trustwaveThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.

URL feed diganti (ketemu census 2026-09-30): Trustwave di-rebrand jadi LevelBlue
(merger AT&T Cybersecurity). URL lama 301 ke `levelblue.com/en-us/.../rss.xml`,
TAPI target redirect itu sendiri sengaja dikosongkan (`<title>[DO NOT USE]
SpiderLabs Blog</title>`, nol `<item>`) -- bukan selector yang salah, feed-nya
memang dibuat mati. Feed yang beneran aktif (ketemu dari `<link rel="alternate"
type="application/rss+xml">` di halaman blog live) di path TANPA `en-us`."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Trustwave(RSSScraper):
    meta = ScraperMeta(
        id="trustwave",
        content_kind="vendor_research",
        source="LevelBlue SpiderLabs (dulu Trustwave)",
        schedule=spread("31 * * * *", "trustwave"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM TRUSTWAVE",
        legacy_script="trustwaveThreat",
    )
    feeds = ("https://www.levelblue.com/blogs/spiderlabs-blog/rss.xml",)
