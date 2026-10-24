"""Sophos -- ditulis manual (codemod Fase 4 nolak nge-generate otomatis).
`ScraperNews/sophosThreat.py` asli MISKLASIFIKASI jadi "bespoke" sama
`classify.py` gara-gara pakai `xmltodict.parse()`, bukan
`defusedxml`/`lxml` -- classifier cuma ngenalin dua library itu buat
family RSS/XPath. Strukturnya sendiri KANONIK banget: fetch satu feed,
loop item, `is_new_and_mark`/`push_job`, gak ada filter apa pun.
`if count == 5: break` (count mulai 1) = 4 item/run.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread


class Sophos(RSSScraper):
    meta = ScraperMeta(
        id="sophos",
        source="Sophos",
        schedule=spread("30 * * * *", "sophos"),
        max_items=4,  # scraper lama: count==5 -> break -- 4 item/run
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM SOPHOS",
        legacy_script="sophosThreat",
    )
    feeds = ("https://www.sophos.com/en-us/blog/feed?id=blt6f15f4f7deaf4242",)
