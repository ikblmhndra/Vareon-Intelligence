"""Group-IB -- diganti ke RSS (census staging 2026-10-01, Fase 10.D). XPath absolut lama
(`/html/body/div[4]/.../a[{i}]/...`) gak match lagi setelah redesign. Feed blog resminya
(`/feed/blogfeed/`, 300+ item) ketemu dari probe path umum. `max_items=10`: feed ini memuat seluruh
arsip blog, jadi tanpa batas kecil run pertama bakal ngantri puluhan artikel lama ke enrichment."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Groupib(RSSScraper):
    meta = ScraperMeta(
        id="groupib",
        source="Group Ib",
        schedule=spread("15 * * * *", "groupib"),
        max_items=10,
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM GROUP IB",
        legacy_script="groupibThreat",
    )
    feeds = ("https://www.group-ib.com/feed/blogfeed/",)
