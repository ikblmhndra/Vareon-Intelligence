"""SentinelOne Labs -- ditulis manual (codemod Fase 4 nolak nge-generate
otomatis karena ada filter di dalam loop). `ScraperNews/sentinelThreat.py`
asli cuma nerima item yang punya kategori "From the Front Lines" atau
"The Good, the Bad and the Ugly" -- TAPI ada kuirk: `skip_status` di-init
`False` dan CUMA di-set di dalam `for cat in item.findall('category')`,
jadi item yang gak punya `<category>` SAMA SEKALI (loop-nya gak pernah
jalan) otomatis LOLOS filter -- beda dari `bleepcomp.py`/`crowdstrike.py`
yang punya bentuk sama tapi default-nya "exclude". Diverifikasi lewat
fixture (item "Agents at Large..." gak punya `<category>` tapi tetap ada
di expected_items) -- kuirk ini SENGAJA dipertahankan, bukan diperbaiki,
karena itu perilaku produksi yang sebenarnya, bukan crash/bug fatal kayak
yang tercatat di KNOWN_BROKEN.md.

**KOREKSI 2026-10-01 (census staging, Fase 10.D):** blog Labs mengganti taksonomi kategorinya --
kedua kategori lama itu gak ada lagi di feed (10 item hari itu semuanya "Adversary", "AI Research", atau
"LABScon"), jadi SEMUA item dibuang filter dan scraper `empty` 20/20 run per 24 jam. Kategori baru yang
setara riset ancaman ditambahkan (`Adversary` = laporan aktor/malware, `AI Research` = penyalahgunaan
agen/model, `LABScon` = rekaman talk konferensi riset); kategori lama dipertahankan. Item tanpa
`<category>` tetap LOLOS (kuirk di atas).
"""

from __future__ import annotations

from xml.etree.ElementTree import Element

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread

_ALLOWED_CATEGORIES = frozenset(
    {
        "From the Front Lines",
        "The Good, the Bad and the Ugly",
        "Adversary",
        "AI Research",
        "LABScon",
    }
)


class Sentinel(RSSScraper):
    meta = ScraperMeta(
        id="sentinel",
        content_kind="vendor_research",
        source="SentinelOne Labs",
        schedule=spread("30 * * * *", "sentinel"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM SENTINELONE",
        legacy_script="sentinelThreat",
    )
    feeds = ("https://www.sentinelone.com/labs/feed/",)

    def _include_item(self, node: Element) -> bool:
        categories = node.findall("category")
        if not categories:
            return True
        return any(cat.text in _ALLOWED_CATEGORIES for cat in categories)
