"""Forcepoint Blog -- port item 10.1c (dormant/disabled di Rundeck,
sebelumnya `ScraperNews/forcepointThreat.py`, Selenium XPath ngambil 2
kartu terbaru dari `/blog` pakai index tetap `div[4]/div[{i}]`). Alerting
lama masih aktif (`push_job`, bukan komentar) -- beda dari 0xtoxin/trellix
yang alert-nya udah mati sebelum diarsipkan.

Situs sekarang (diverifikasi live 2026-09-30) gak punya RSS -- daftar
artikelnya react/next-render, dan strukturnya BUKAN kartu seragam per-index
kayak yang diasumsikan script lama: kartu ke-1 (hero, judul `<h2>` di
dalam beberapa `<div>` nested) beda struktur dari kartu grid di bawahnya
(judul `<h4>` langsung anak `<a>`), dan di antara kartu ada blok non-artikel
(newsletter signup dsb) yang bikin index `div[N]`-nya lompat-lompat. Makanya
`indexed=False` (mode zipped) + XPath union `h2`/`h4`, bukan `{i}` tetap
seperti script lama -- lebih tahan kalau CMS nyisipin blok baru di antara
kartu."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread


class Forcepoint(XPathScraper):
    meta = ScraperMeta(
        id="forcepoint",
        content_kind="vendor_research",
        source="Forcepoint",
        schedule=spread("50 * * * *", "forcepoint"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=5,
        tags=("migrated", "fase-10.1c"),
        legacy_label="NEW ARTICLE FROM FORCEPOINT",
        legacy_script="forcepointThreat",
    )
    url = "https://www.forcepoint.com/blog"
    base_url = "https://www.forcepoint.com"
    indexed = False
    title_xpath = "//main//a[h4]/h4/text() | //main//a[.//h2]//h2/text()"
    link_xpath = "//main//a[h4]/@href | //main//a[.//h2]/@href"
