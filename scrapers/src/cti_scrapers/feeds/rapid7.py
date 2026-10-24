"""Rapid7 -- ditulis manual (codemod Fase 4 nolak nge-generate otomatis
karena ada filter kategori + parser XML yang beda). `ScraperNews/rapid7Threat.py`
asli:

1. Parse pakai `lxml.etree.XMLParser(recover=True)`, BUKAN `defusedxml` --
   feed-nya butuh mode lenient (bukan cuma smart-escape `&` kayak biasa).
   `resolve_entities=False` + `no_network=True` dipasang manual di sini buat
   nutup XXE (defusedxml gak dipakai buat kasus ini, jadi safety-nya harus
   eksplisit, bukan bawaan seperti scraper RSS biasa).
2. Cuma nerima item yang kategorinya salah satu dari "Emergent Threat
   Response"/"Research"/"Threat Intel"/"Labs".

Sama kayak scraper lain yang punya rantai smart-escape `&` (lihat
`families/rss.py` -- `BARE_AMPERSAND`), dipakai ulang di sini persis, TANPA
`html.unescape()` (source asli emang gak manggil itu buat file ini).
"""

from __future__ import annotations

from collections.abc import Iterator

from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.errors import ParseError
from cti_scraper.families.rss import escape_bare_ampersands
from cti_scraper.items import ArticleItem
from cti_scraper.schedule import spread
from lxml import etree

_ALLOWED_CATEGORIES = {"Emergent Threat Response", "Research", "Threat Intel", "Labs"}


class Rapid7(BaseScraper):
    meta = ScraperMeta(
        id="rapid7",
        content_kind="vendor_research",
        source="Rapid7",
        schedule=spread("2 * * * *", "rapid7"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM RAPID7",
        legacy_script="rapid7Threat",
    )
    feed_url = "https://www.rapid7.com/rss.xml"

    def fetch(self, ctx: ScrapeContext) -> Iterator[ArticleItem]:
        resp = ctx.http.get(self.feed_url)
        text = resp.text.lstrip("﻿ \t\r\n")
        text = escape_bare_ampersands(text)

        parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
        root = etree.fromstring(text.encode("utf-8"), parser)
        if root is None:
            raise ParseError(f"{self.feed_url}: XML gak valid, bahkan dengan recover=True")

        found = 0
        for item in root.findall(".//item"):
            if found >= self.meta.max_items:
                return
            if not any(cat.text in _ALLOWED_CATEGORIES for cat in item.findall("category")):
                continue

            title_el = item.find("title")
            link_el = item.find("link")
            if title_el is None or link_el is None:
                continue
            title = (title_el.text or "").strip()
            url = (link_el.text or "").strip()
            if not title or not url:
                continue

            found += 1
            yield ArticleItem(title=title, url=url, posted_on=ctx.now.date())
