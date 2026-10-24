"""Cloudflare -- diganti ke RSS blog (census staging 2026-10-01, Fase 10.D). Halaman
`resource-hub/?resourcetype=Report` (laporan berkala, mis. DDoS threat report) gak match XPath absolut
lama lagi. **Scope BERUBAH**: laporan-laporan itu jarang terbit dan gak punya feed sendiri, jadi
diganti feed tag `security` di blog Cloudflare (Ghost, 20 post terbaru) -- yang di dalamnya juga
memuat ringkasan laporan threat/DDoS mereka. Kalau laporan resource-hub memang wajib dipantau
terpisah, itu butuh scraper XPath baru, bukan ganti URL."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Cloudflare(RSSScraper):
    meta = ScraperMeta(
        id="cloudflare",
        content_kind="vendor_research",
        source="Cloudflare",
        schedule=spread("1 * * * *", "cloudflare"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM CLOUDFLARE",
        legacy_script="cloudflareThreat",
    )
    feeds = ("https://blog.cloudflare.com/tag/security/rss/",)
