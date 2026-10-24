"""Sysdig -- URL feed diganti (census staging 2026-10-01, Fase 10.D). Situsnya pindah ke Webflow:
`sysdig.com/blog/topic/threat-research/feed/` sekarang 404. Feed yang hidup: `/blog/rss.xml` (100 item,
SELURUH blog -- lebih luas dari topik threat-research yang dulu; feed-nya gak membawa kategori jadi
gak bisa difilter, sisanya dibuang klasifikasi enrichment).

Jebakan: `<link>` di feed ini nunjuk ke host staging Webflow (`webflow.sysdig.com`), bukan host
publik. `xml_fixups` ngganti host-nya SEBELUM parse, supaya URL artikel yang tersimpan & di-alert
itu `www.sysdig.com` (dan dedup-nya cocok sama URL canonical). `max_items=10`: feed memuat 100 item."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Sysdig(RSSScraper):
    meta = ScraperMeta(
        id="sysdig",
        source="Sysdig",
        schedule=spread("32 * * * *", "sysdig"),
        max_items=10,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM SYSDIG",
        legacy_script="sysdigThreat",
    )
    feeds = ("https://www.sysdig.com/blog/rss.xml",)
    xml_fixups = (("https://webflow.sysdig.com/", "https://www.sysdig.com/"),)
