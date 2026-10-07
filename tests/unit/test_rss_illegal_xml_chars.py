"""Fix ketemu port `toxinlabs.py` (Fase 10.1c, 2026-09-30): feed Jekyll
`0xtoxin.github.io/feed.xml` nge-paste konten IOC/malware analysis mentah
yang bawa byte kontrol ilegal XML 1.0 (`\\x01`-`\\x05`), bikin `defusedxml`
nolak "not well-formed" walau feed-nya sendiri valid Atom. Fix-nya generik
di `RSSScraper._parse_feed` (`strip_illegal_xml_chars`), bukan `xml_fixups`
per-scraper -- feed APAPUN yang isinya nge-paste output terminal/hexdump
bisa kena masalah yang sama.
"""

from __future__ import annotations

import httpx
from cti_scraper.families.rss import strip_illegal_xml_chars
from cti_scrapers.feeds.toxinlabs import ToxinLabs

from tests.unit.scraper_helpers import make_ctx

# Potongan nyata dari `https://0xtoxin.github.io/feed.xml` (ditarik 2026-09-30) --
# entry "Kraken - The Deep Sea Lurker Part 1" beneran bawa byte 0x02 0x02 di tengah
# konten IOC yang di-paste, sama seperti yang bikin dry-run gagal pas port.
ATOM_FEED_WITH_ILLEGAL_BYTES = (
    b'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
    b"<title>Toxin Labs</title>"
    b"<entry>"
    b'<title type="html">Kraken - The Deep Sea Lurker Part 1</title>'
    b'<link href="https://0xtoxin.github.io/malware%20analysis/KrakenKeylogger-pt1/"'
    b' rel="alternate" type="text/html" />'
    b"<published>2023-05-20T00:00:00+00:00</published>"
    b"<id>https://0xtoxin.github.io/malware%20analysis/KrakenKeylogger-pt1</id>"
    b'<content type="html">[+] PersonalEmail - redacted@example.com\x02\x02\n[+] PersonalEmail'
    b"</content>"
    b"</entry>"
    b"<entry>"
    b'<title type="html">Clean Entry</title>'
    b'<link href="https://0xtoxin.github.io/clean-entry/" rel="alternate" type="text/html" />'
    b"<published>2023-08-06T00:00:00+00:00</published>"
    b"<id>https://0xtoxin.github.io/clean-entry</id>"
    b"</entry>"
    b"</feed>"
)


def test_strip_illegal_xml_chars_removes_control_bytes_but_keeps_tab_lf_cr() -> None:
    text = "before\x02\x02middle\tend\nline\r\n"

    cleaned = strip_illegal_xml_chars(text)

    assert cleaned == "beforemiddle\tend\nline\r\n"


def test_toxinlabs_parses_despite_stray_control_bytes_in_one_entry() -> None:
    ctx = make_ctx(ToxinLabs, lambda r: httpx.Response(200, content=ATOM_FEED_WITH_ILLEGAL_BYTES))

    items = list(ToxinLabs().fetch(ctx))

    assert [i.title for i in items] == [
        "Kraken - The Deep Sea Lurker Part 1",
        "Clean Entry",
    ]
    assert items[0].url == "https://0xtoxin.github.io/malware%20analysis/KrakenKeylogger-pt1/"
