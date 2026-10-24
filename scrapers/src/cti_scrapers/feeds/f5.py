"""F5 Labs -- ditulis manual (codemod Fase 4 nolak nge-generate otomatis
karena ada filter tahun di dalam loop). `ScraperNews/f5Threat.py` asli cuma
nerima item yang `pubDate`-nya di TAHUN INI (`pubDate.split(" ")[3]`).
Feed-nya diverifikasi (lihat fixture) gak punya entity HTML bernama atau
CDATA yang butuh perlakuan khusus -- default `RSSScraper` (smart-escape
bare `&`, gak butuh `xml_fixups`/`html_unescape`) udah cukup.
"""

from __future__ import annotations

from datetime import datetime
from xml.etree.ElementTree import Element

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class F5(RSSScraper):
    meta = ScraperMeta(
        id="f5",
        source="F5 Labs",
        schedule=spread("46 * * * *", "f5"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM F5",
        legacy_script="f5Threat",
    )
    feeds = ("https://www.f5.com/labs/rss-feeds/all.xml",)

    def _include_item(self, node: Element) -> bool:
        pub_date = node.find("pubDate")
        if pub_date is None or not pub_date.text:
            return False
        parts = pub_date.text.split(" ")
        if len(parts) < 4:
            return False
        return parts[3] == str(datetime.now().year)
