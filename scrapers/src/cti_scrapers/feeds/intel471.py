"""Intel 471 -- diganti ke RSS blog (census staging 2026-10-01, Fase 10.D). XPath absolut lama untuk
`/resources/whitepapers` gak match lagi. **Scope BERUBAH**: whitepaper gak punya feed; yang dipantau
sekarang blog (`/blog/feed`, 50 item), yang justru output CTI utama mereka. Konsekuensinya whitepaper
baru TIDAK lagi ke-alert lewat scraper ini (jarang terbit). `max_items=10`: feed memuat 50 item.

**Belum terbukti stabil (2026-10-01):** situsnya di balik Vercel dan membalas HTTP 429 (tanpa
`Retry-After`) setelah beberapa request berturut-turut, dari DUA IP berbeda (Mac dev dan host staging);
request pertama berhasil (50 item). Polling per jam jauh lebih jarang dari probe saat investigasi, jadi
mungkin aman -- tapi kalau 429 menetap di staging/produksi, ini kandidat waiver (proteksi mereka, gak
dicoba dilewatin), bukan diperbaiki dengan menaikkan frekuensi atau ganti User-Agent."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Intel471(RSSScraper):
    meta = ScraperMeta(
        id="intel471",
        source="Intel471",
        schedule=spread("0 * * * *", "intel471"),
        max_items=10,
        tags=("migrated",),
        legacy_label="NEW ARTICLE/PAPER FROM INTEL471",
        legacy_script="intel471Threat",
    )
    feeds = ("https://www.intel471.com/blog/feed",)
