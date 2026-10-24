"""CrowdStrike -- ditulis manual (codemod Fase 4 nolak nge-generate otomatis
karena ada filter di dalam loop). `ScraperNews/crowdstrikeThreat.py` asli
cuma nerima item yang punya `<category>Counter Adversary Operations</category>`
-- filter ini udah dikonfirmasi SAH lewat investigasi Fase 0.5 (bukan bug,
lihat KNOWN_BROKEN.md: feed-nya emang cuma 1 item/hari yang lolos filter).

**KOREKSI 2026-10-01 (census staging, Fase 10.D):** kesimpulan "filter sah" itu sudah BASI. Blog
CrowdStrike mengganti nama kategorinya jadi "Threat Hunting & Intel" (3 dari 10 item feed hari itu),
dan "Counter Adversary Operations" gak muncul sama sekali -> 0 item lolos filter, 20/20 run per 24 jam
`empty`. Sekarang menerima KEDUA nama (nama lama dipertahankan kalau mereka mengembalikannya).
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread

_ALLOWED_CATEGORIES = frozenset({"Counter Adversary Operations", "Threat Hunting & Intel"})


class Crowdstrike(RSSScraper):
    meta = ScraperMeta(
        id="crowdstrike",
        content_kind="vendor_research",
        source="CrowdStrike",
        schedule=spread("30 * * * *", "crowdstrike"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM CROWDSTRIKE",
        legacy_script="crowdstrikeThreat",
    )
    feeds = ("https://www.crowdstrike.com/en-us/blog/feed",)
    xml_fixups = (("&ndash;", ""), ("&", "&amp;"))
    html_unescape = True  # feed lama pakai html.unescape() sebelum parse XML

    def _include_item(self, node: Element) -> bool:
        return any(cat.text in _ALLOWED_CATEGORIES for cat in node.findall("category"))
