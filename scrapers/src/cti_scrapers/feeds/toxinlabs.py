"""0xToxin (Toxin Labs) -- port item 10.1c (dormant/disabled di Rundeck,
sebelumnya `ScraperNews/stopped_script/0xToxinThreat.py`, Selenium XPath
ngambil 5 kartu terbaru dari homepage). Alert-nya SENDIRI udah dikomentar
di script lama (`# send_alert(...)`) -- gak pernah beneran ngirim ke
produksi, cuma nge-print.

**Bukan Selenium/browser sama sekali** -- homepage-nya nyediain Atom feed
resmi (`https://0xtoxin.github.io/feed.xml`, Jekyll), jadi `RSSScraper`
biasa cukup, sama kayak pola migrasi Fase 4 lain.

Catatan penting buat yang lanjutin: blog-nya **mati total sejak Agustus
2023** (`<updated>` feed = 2023-08-13, entry terbaru = 2023-08-06) --
diverifikasi 2026-09-30, feed-nya masih valid & bisa diparse, cuma isinya
gak pernah nambah lagi. Scraper ini kemungkinan besar gak akan pernah
nge-trigger alert baru; tetap diport buat kelengkapan port, BUKAN karena
diharapkan aktif."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class ToxinLabs(RSSScraper):
    meta = ScraperMeta(
        id="0xtoxin",
        content_kind="vendor_research",
        source="0xToxin (Toxin Labs)",
        schedule=spread("40 * * * *", "0xtoxin"),
        tags=("migrated", "fase-10.1c"),
        legacy_label="NEW RECENT ARTICLE FROM 0xToxin",
        legacy_script="0xToxinThreat",
    )
    feeds = ("https://0xtoxin.github.io/feed.xml",)
    item_path = f".//{_ATOM_NS}entry"
    title_path = f"{_ATOM_NS}title"
    link_path = f"{_ATOM_NS}link"
    link_attr = "href"
