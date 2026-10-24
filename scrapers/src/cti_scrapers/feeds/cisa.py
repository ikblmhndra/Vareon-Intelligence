"""CISA -- ditulis manual (codemod Fase 4 nolak nge-generate otomatis
karena ada sanitasi byte + filter di dalam loop). `ScraperNews/cisaThreat.py`
asli:

1. Buang byte XML yang gak valid (`remove_invalid_xml_bytes` -- filter
   berbasis RANGE BYTE, beda dari `xml_fixups` yang cuma string `.replace()`
   biasa, jadi gak bisa diekspresiin lewat field deklaratif yang ada).
2. Skip item yang URL-nya ngandung "news-events/ics-advisories/" (cuma mau
   cybersecurity advisories umum, bukan ICS-specific).

**WAIVER 2026-10-01 (census staging, Fase 10.D) -- `enabled=False`.** `all.xml` dibalas HTTP 403 "Access Denied" (WAF Akamai) untuk klien kita, konsisten 19/19 run per 24 jam -- BUKAN flaky seperti dugaan awal (dulu dikira cuma XML rusak sesekali). Proteksi bot gak dicoba dilewatin; kalau mau dipantau, perlu jalur yang memang disediakan CISA. Advisory paling penting (KEV) tetap dipantau scraper `cisa_kev`.
Diaktifkan lagi kalau sumbernya balik/ada jalur baru -- lihat `docs/KNOWN_BROKEN.md`.
"""

from __future__ import annotations

from collections.abc import Iterator
from xml.etree.ElementTree import Element
from xml.etree.ElementTree import ParseError as XmlParseError

import defusedxml.ElementTree as ET
from cti_scraper.base import ScrapeContext, ScraperMeta
from cti_scraper.errors import ParseError
from cti_scraper.families.rss import RSSScraper
from cti_scraper.items import ArticleItem
from cti_scraper.schedule import spread


def _remove_invalid_xml_bytes(raw: bytes) -> str:
    clean = bytearray(
        b for b in raw if 0x20 <= b <= 0xD7FF or 0xE000 <= b <= 0xFFFD or b in (0x09, 0x0A, 0x0D)
    )
    return clean.decode("utf-8", "ignore")


class Cisa(RSSScraper):
    meta = ScraperMeta(
        id="cisa",
        content_kind="advisory",
        source="CISA",
        schedule=spread("1 * * * *", "cisa"),
        enabled=False,  # waiver 10.D, lihat docstring
        tags=("migrated",),
        legacy_label="NEW CYBERSECURITY ADVISORIES FROM CISA",
        legacy_script="cisaThreat",
    )
    feeds = ("https://www.cisa.gov/cybersecurity-advisories/all.xml",)

    def _parse_feed(self, ctx: ScrapeContext, feed_url: str) -> Iterator[ArticleItem]:
        resp = ctx.http.get(feed_url)
        text = _remove_invalid_xml_bytes(resp.content)

        try:
            root = ET.fromstring(text.encode("utf-8"))
        except XmlParseError as e:
            raise ParseError(f"{feed_url}: XML gak valid -- {e}") from e

        nodes = root.findall(self.item_path)
        if not nodes:
            raise ParseError(f"{feed_url}: gak ada node di item_path={self.item_path!r}")

        for node in nodes:
            if not self._include_item(node):
                continue
            item = self._parse_item(node, ctx)
            if item is not None:
                yield item

    def _include_item(self, node: Element) -> bool:
        link_el = node.find("link")
        link = (link_el.text or "") if link_el is not None else ""
        return "news-events/ics-advisories/" not in link
