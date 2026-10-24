"""Cyber Security News -- ditulis manual (codemod Fase 4 nolak nge-generate
otomatis karena ada `print(featured_title)` di dalam loop -- bukan filter,
cuma debug leftover, tapi extractor sengaja gak mau nebak statement yang
gak dikenal).

Satu hal lain yang butuh perhatian manual: feed-nya (`cybersecuritynews.com`)
beneran punya entity HTML bernama (`&nbsp;`, `&mdash;` -- BUKAN entity XML
bawaan) di teks title, bukan di dalam CDATA. `RSSScraper` default nge-apply
smart-escape SEBELUM `html_unescape` (urutan itu WAJIB buat scraper yang
xml_fixups-nya nyentuh CDATA, lihat `embeeresearch.py`/komentar di
`families/rss.py` -- coba dibalik pernah bikin regresi di situ), tapi
urutan itu gak nyelesain "&nbsp;"/"&mdash;" di sini karena scraper ini gak
punya xml_fixups yang nyentuh CDATA sama sekali. Makanya di-override:
unescape DULU (`html.unescape()` ngeberesin &nbsp;/&mdash; jadi karakter
Unicode asli), BARU smart-escape (buat & bare sisa hasil unescape-nya
&amp; -- feed ini punya banyak).
"""

from __future__ import annotations

import html
from collections.abc import Iterator
from xml.etree.ElementTree import ParseError as XmlParseError

import defusedxml.ElementTree as ET
from cti_scraper.base import ScrapeContext, ScraperMeta
from cti_scraper.errors import ParseError
from cti_scraper.families.rss import RSSScraper, escape_bare_ampersands
from cti_scraper.items import ArticleItem
from cti_scraper.schedule import spread


class Cybersecnews(RSSScraper):
    meta = ScraperMeta(
        id="cybersecnews",
        source="Cyber Security News",
        schedule=spread("0 * * * *", "cybersecnews"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM CYBERSECURITY NEWS",
        legacy_script="cybersecnewsThreat",
    )
    feeds = ("https://cybersecuritynews.com/feed/",)

    def _parse_feed(self, ctx: ScrapeContext, feed_url: str) -> Iterator[ArticleItem]:
        resp = ctx.http.get(feed_url)
        text = resp.text.lstrip("﻿ \t\r\n")
        text = html.unescape(text)  # &nbsp;/&mdash; -> karakter asli DULU
        text = escape_bare_ampersands(text)  # baru escape & bare sisanya

        try:
            root = ET.fromstring(text.encode("utf-8"))
        except XmlParseError as e:
            raise ParseError(f"{feed_url}: XML gak valid -- {e}") from e

        nodes = root.findall(self.item_path)
        if not nodes:
            raise ParseError(f"{feed_url}: gak ada node di item_path={self.item_path!r}")

        for node in nodes:
            item = self._parse_item(node, ctx)
            if item is not None:
                yield item
