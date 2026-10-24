"""RSSScraper -- declarative RSS/Atom. Nutupin ~142 dari 241 scraper lama
(~59%, family paling besar). Subclass, isi `feeds`, selesai.

Bandingkan sama `gbHackerThreat.py` asli (43 baris): UA header, cabang
status-code, rantai `.replace()` ad-hoc buat entity malformed, loop
`is_new_and_mark`/`push_job` -- semua itu boilerplate yang di sini jadi
default yang jalan. Hasil migrasinya di
`scrapers/src/cti_scrapers/feeds/gbhackers.py` cuma ~10 baris.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import ClassVar
from urllib.parse import urljoin
from xml.etree.ElementTree import Element
from xml.etree.ElementTree import ParseError as XmlParseError

import defusedxml.ElementTree as ET

from cti_scraper.base import BaseScraper, ScrapeContext
from cti_scraper.errors import ParseError
from cti_scraper.items import ArticleItem

BARE_AMPERSAND = re.compile(r"&(?!amp;|lt;|gt;|quot;|apos;|#[0-9]+;|#x[0-9A-Fa-f]+;)")
"""`&` yang BUKAN awal entity valid -- 3 scraper lama (f5, rapid7,
cybersecnews) punya regex identik ini sebagai pengganti rantai `.replace()`
blind. Lebih presisi: cuma escape `&` yang beneran bare, entity yang udah
valid (termasuk numerik kayak "&#038;") gak disentuh sama sekali -- gak
butuh langkah unescape susulan kayak pola `xml_fixups`+`html_unescape`."""

_CDATA_SPLIT = re.compile(r"(<!\[CDATA\[.*?\]\]>)", re.DOTALL)

_ILLEGAL_XML_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
"""Karakter kontrol yang XML 1.0 gak izinkan sama sekali (tab/LF/CR
dikecualikan). Ketauan lewat port `toxinlabs.py` (Fase 10.1c, 2026-09-30):
feed Jekyll-nya nge-paste konten analisis malware/IOC mentah yang masih
bawa byte kontrol (`\\x01`-`\\x05`), bikin `defusedxml` nolak "not
well-formed". Strip-nya generik di sini, bukan `xml_fixups` per-scraper --
feed APAPUN yang isinya nge-paste output terminal/hexdump bisa kena
masalah yang sama."""


def strip_illegal_xml_chars(text: str) -> str:
    return _ILLEGAL_XML_CHARS.sub("", text)


def escape_bare_ampersands(text: str) -> str:
    """`BARE_AMPERSAND.sub()` PER-SEGMEN, ngelewatin isi `<![CDATA[...]]>`
    utuh -- konten CDATA MEMANG dikecualikan dari entity processing XML
    (itu tujuan CDATA), jadi `&` bare di dalamnya udah valid apa adanya.
    Ketauan dari `wiz.py`: title CDATA yang punya "CVE-A & CVE-B" kena
    escape jadi "&amp;" gara-gara regex whole-text yang gak CDATA-aware --
    XML parser gak decode isi CDATA, jadi "&amp;" nyangkut literal di title
    final, bukan balik jadi "&"."""
    parts = _CDATA_SPLIT.split(text)
    return "".join(
        part if part.startswith("<![CDATA[") else BARE_AMPERSAND.sub("&amp;", part)
        for part in parts
    )


class RSSScraper(BaseScraper):
    __abstract__ = True

    feeds: ClassVar[tuple[str, ...]]
    item_path: ClassVar[str] = ".//item"
    """XPath-lite ElementTree, mis. ".//item" (RSS) atau
    ".//{http://www.w3.org/2005/Atom}entry" (Atom -- namespace wajib eksplisit)."""
    title_path: ClassVar[str] = "title"
    link_path: ClassVar[str] = "link"
    date_path: ClassVar[str | None] = "pubDate"
    """Elemen tanggal utama; kalau tidak ada/tidak terbaca dicoba `_DATE_FALLBACK_PATHS` (Atom,
    Dublin Core), baru waktu scrape. `None` = sengaja pakai waktu scrape (feed yang tanggalnya
    salah). Dulu 61 scraper hasil migrasi memasang `None` demi paritas kode lama, sehingga
    postingan lama yang masih ada di feed tampil sebagai berita hari ini (audit UI U10)."""
    link_attr: ClassVar[str | None] = None
    """None: ambil `.text` node link (RSS). Diisi "href": ambil attribute
    itu (Atom, `<link href="..."/>`)."""
    base_url: ClassVar[str] = ""
    """Prefix buat link relatif. Kosongin kalau feed-nya selalu absolut
    (mayoritas kasus)."""
    xml_fixups: ClassVar[tuple[tuple[str, str], ...]] = ()
    """Pasangan (cari, ganti) di-apply ke teks MENTAH sebelum parse XML.
    Lifted dari rantai `.replace()` ad-hoc yang tiap scraper lama punya
    sendiri buat entity yang malformed -- kebanyakan scraper hasil migrasi
    gak butuh ini sama sekali karena defusedxml + recover di bawah udah
    nanganin kasus umum."""
    html_unescape: ClassVar[bool] = False
    """True kalau scraper lama bungkus `ET.fromstring(html.unescape(...))`.
    Perlu di-apply SETELAH `xml_fixups`, SEBELUM parse XML: `xml_fixups`
    biasanya blind-escape semua `&` jadi `&amp;` (termasuk entity numerik
    yang udah valid kayak "&#038;", jadi double-escaped), dan unescape ini
    ngebalikin satu layer-nya -- 51/52 scraper RSS lama yang punya
    xml_fixups juga bungkus html.unescape(), jadi ini bukan kasus khusus."""

    def fetch(self, ctx: ScrapeContext) -> Iterator[ArticleItem]:
        found_total = 0
        for feed_url in self.feeds:
            for item in self._parse_feed(ctx, feed_url):
                if found_total >= self.meta.max_items:
                    return
                found_total += 1
                yield item

    def _parse_feed(self, ctx: ScrapeContext, feed_url: str) -> Iterator[ArticleItem]:
        resp = ctx.http.get(feed_url)
        # BOM dan/atau CRLF sebelum "<?xml ...?>" bikin parse gagal (deklarasi
        # XML wajib jadi karakter PERTAMA) -- 28 scraper lama defensif soal ini
        # (`.decode("utf-8-sig")` dan/atau `.lstrip()`). Selalu aman di-strip:
        # feed yang udah rapi gak kena dampak apa-apa.
        text = resp.text.lstrip("\ufeff \t\r\n")
        text = strip_illegal_xml_chars(text)
        for old, new in self.xml_fixups:
            text = text.replace(old, new)
        text = escape_bare_ampersands(text)
        if self.html_unescape:
            text = html.unescape(text)

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
        """Override buat filter per-item SEBELUM di-parse (mis. kategori,
        pola URL) -- default-nya semua item lolos. `node` itu element
        `<item>`/`<entry>` mentah, jadi bisa cek sibling kayak `<category>`
        yang gak ada di `ArticleItem` hasil parse. Contoh: `crowdstrike.py`
        cuma nerima kategori "Counter Adversary Operations" (filter ini
        udah dikonfirmasi SAH lewat Fase 0.5, lihat KNOWN_BROKEN.md)."""
        return True

    def _parse_item(self, node: Element, ctx: ScrapeContext) -> ArticleItem | None:
        title_el = node.find(self.title_path)
        link_el = node.find(self.link_path)
        if title_el is None or link_el is None:
            return None

        title = (title_el.text or "").strip()
        url = link_el.get(self.link_attr, "") if self.link_attr else (link_el.text or "").strip()
        if not title or not url:
            return None
        if self.base_url and not url.startswith("http"):
            url = urljoin(self.base_url, url)

        posted_on = ctx.now.date()
        if self.date_path is not None:
            for path in (self.date_path, *_DATE_FALLBACK_PATHS):
                date_el = node.find(path)
                parsed = _parse_feed_date(date_el.text) if date_el is not None else None
                if parsed is not None:
                    # Tanggal masa depan (zona waktu/feed ngawur) tidak boleh mendahului hari ini.
                    posted_on = min(parsed, posted_on)
                    break

        return ArticleItem(title=title, url=url, posted_on=posted_on)


_DATE_FALLBACK_PATHS = (
    "pubDate",
    "{http://www.w3.org/2005/Atom}published",
    "{http://www.w3.org/2005/Atom}updated",
    "{http://purl.org/dc/elements/1.1/}date",
)


def _parse_feed_date(text: str | None) -> date | None:
    """RFC 822 (RSS `pubDate`) atau ISO 8601 (Atom, Dublin Core)."""
    if not text or not text.strip():
        return None
    text = text.strip()
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None
