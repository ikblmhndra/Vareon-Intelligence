"""SOCRadar -- ditulis manual (codemod Fase 4 nolak nge-generate otomatis).
`ScraperNews/socradarThreat.py` asli DIBUNGKUS `for i in range(1, 5)`, tapi
XPath-nya gak pernah pakai `{i}` sama sekali -- tiap iterasi nge-query
XPath TETAP yang sama persis. `is_new_and_mark()` makainya key
`title+url`, jadi begitu iterasi pertama nge-mark key itu "udah pernah
diliat", 3 iterasi sisanya otomatis di-skip DALAM run yang sama --
efeknya scraper ini SELALU cuma ngambil SATU item per run (posisi tetap),
walau kelihatannya loop 4x. Bukan diakalin di ekstraktor: `max_items=1`,
gak ada `{i}` di XPath sama sekali -- `.format(i=1)` di string tanpa
placeholder itu no-op, aman.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread

_CARD = '//*[@id="list"]/div[2]/div/div/div/div[2]/h5/strong/a'


class Socradar(XPathScraper):
    meta = ScraperMeta(
        id="socradar",
        content_kind="vendor_research",
        source="SOCRadar",
        schedule=spread("0 * * * *", "socradar"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=1,  # scraper lama: XPath fixed, gak ada {i} -- selalu 1 item/run
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM SOCRADAR",
        legacy_script="socradarThreat",
    )
    url = "https://socradar.io/blog/"
    title_xpath = f"{_CARD}/text()"
    link_xpath = f"{_CARD}/@href"
