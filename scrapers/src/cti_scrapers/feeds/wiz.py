"""Wiz -- ditulis manual (codemod Fase 4 nolak nge-generate otomatis).
`ScraperNews/wizThreat.py` asli punya `if count == 10: break` + `count += 1`
di dalam loop -- itu cuma cap manual 9 item per run (`count` mulai dari 1,
break SEBELUM proses item ke-10), setara `ScraperMeta.max_items=9` bawaan
framework. Cek `if title is None: continue`-nya juga udah default behavior
`RSSScraper._parse_item()` (skip item yang title/link-nya kosong).
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Wiz(RSSScraper):
    meta = ScraperMeta(
        id="wiz",
        content_kind="vendor_research",
        source="Wiz",
        schedule=spread("47 * * * *", "wiz"),
        max_items=9,  # scraper lama: count==10 -> break -- 9 item/run
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM WIZ",
        legacy_script="wizThreat",
    )
    feeds = ("https://www.wiz.io/feed/rss.xml",)
