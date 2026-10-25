"""Akamai -- ditulis manual (codemod Fase 4 nolak nge-generate otomatis
karena ada filter di dalam loop). `ScraperNews/akamaiThreat.py` asli cuma
nerima item yang URL-nya ngandung "security-research" atau "security", DAN
ngandung tahun ini.
"""

from __future__ import annotations

from datetime import datetime
from xml.etree.ElementTree import Element

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Akamai(RSSScraper):
    meta = ScraperMeta(
        id="akamai",
        content_kind="vendor_research",
        source="Akamai",
        schedule=spread("31 * * * *", "akamai"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM AKAMAI",
        legacy_script="akamaiThreat",
    )
    feeds = ("https://feeds.feedburner.com/akamai/blog",)

    def _include_item(self, node: Element) -> bool:
        link_el = node.find("link")
        link = (link_el.text or "") if link_el is not None else ""
        if "security-research" not in link and "security" not in link:
            return False
        return str(datetime.now().year) in link
