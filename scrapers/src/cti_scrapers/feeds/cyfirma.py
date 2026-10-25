"""CYFIRMA Research -- referensi family XPath, runtime="light" (httpx+lxml,
gak butuh Chromium). Bandingkan sama `ScraperNews/cyfirmaThreat.py` asli:
XPath yang sama persis, tapi di sana ditulis manual `requests.get` +
`lxml.html.fromstring` + loop `range(1,7)` + `is_new_and_mark`/`push_job`.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread


class Cyfirma(XPathScraper):
    meta = ScraperMeta(
        id="cyfirma",
        content_kind="vendor_research",
        source="CYFIRMA",
        schedule=spread("*/30 * * * *", "cyfirma"),
        runtime="light",
        max_items=6,  # scraper lama: range(1, 7) -> 6 kartu
        tags=("vendor",),
        legacy_label="NEW ARTICLE FROM CYFIRMA",
        legacy_script="cyfirmaThreat",
    )
    url = "https://www.cyfirma.com/research/"
    title_xpath = "/html/body/div[2]/div[1]/section[3]/div/div/div[1]/div[{i}]/div[2]/h6/a/text()"
    link_xpath = "/html/body/div[2]/div[1]/section[3]/div/div/div[1]/div[{i}]/div[2]/h6/a/@href"
