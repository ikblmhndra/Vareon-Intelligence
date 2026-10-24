"""Bleeping Computer -- ditulis manual (codemod Fase 4 nolak nge-generate
otomatis karena ada filter di dalam loop). `ScraperNews/bleepcompThreat.py`
asli cuma nerima item yang punya `<category>Security</category>`.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Bleepcomp(RSSScraper):
    meta = ScraperMeta(
        id="bleepcomp",
        source="Bleeping Computer",
        schedule=spread("30 * * * *", "bleepcomp"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM BLEEPING COMPUTER",
        legacy_script="bleepcompThreat",
    )
    feeds = ("https://www.bleepingcomputer.com/feed/",)
    xml_fixups = (("&ndash;", ""), ("&", "&amp;"))
    html_unescape = True  # feed lama pakai html.unescape() sebelum parse XML

    def _include_item(self, node: Element) -> bool:
        return any(cat.text == "Security" for cat in node.findall("category"))
