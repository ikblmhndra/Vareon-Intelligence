"""Huntress -- diganti ke RSS (census staging 2026-10-01, Fase 10.D). Selector CSS-class lama
(`persistent-link blog-index-card-link w-inline-block`) gak match lagi. Feed resminya
(`/blog/rss.xml`, 700+ item) ketemu dari probe path umum. Scope SEDIKIT LEBIH LUAS dari versi lama:
halaman lama difilter kategori (Threat Analysis, Huntress News, Cybersecurity Trends), feed ini
tidak membawa kategori jadi tidak bisa difilter -- post produk/marketing ikut masuk dan dibuang
klasifikasi enrichment kalau bukan CTI. `max_items=10`: feed memuat seluruh arsip blog."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Huntress(RSSScraper):
    meta = ScraperMeta(
        id="huntress",
        content_kind="vendor_research",
        source="Huntress",
        schedule=spread("30 * * * *", "huntress"),
        max_items=10,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM HUNTRESS",
        legacy_script="huntressThreat",
    )
    feeds = ("https://www.huntress.com/blog/rss.xml",)
