"""Trend Micro Research -- referensi family XPath, runtime="browser"
(Playwright, dibutuhin buat situs yang render konten via JS). Bandingkan
sama `ScraperNews/trendmicroThreat.py` asli: `sync_playwright()` manual,
`page.locator(...).text_content()`/`.get_attribute("href")`, loop
`range(1,5)` dibungkus `try/except TimeoutError: continue` per kartu --
semua itu jadi `_get_html()`+`_extract_indexed()` bawaan framework.
"""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.schedule import spread

_CARD = "/html/body/div[2]/div/div[2]/section/div[1]/article[{i}]/div/div[1]/h3/a"


class TrendMicro(XPathScraper):
    meta = ScraperMeta(
        id="trendmicro",
        content_kind="vendor_research",
        source="Trend Micro Research",
        schedule=spread("0 */2 * * *", "trendmicro"),
        runtime="browser",
        rate_limit="6/minute",
        max_items=4,  # scraper lama: range(1, 5) -> 4 kartu
        tags=("vendor",),
        legacy_label="NEW ARTICLE FROM TRENDMICRO",
        legacy_script="trendmicroThreat",
    )
    url = (
        "https://www.trendmicro.com/en_us/research.html"
        "?category=trend-micro-research:article-type/latest-news"
    )
    title_xpath = f"{_CARD}/text()"
    link_xpath = f"{_CARD}/@href"
