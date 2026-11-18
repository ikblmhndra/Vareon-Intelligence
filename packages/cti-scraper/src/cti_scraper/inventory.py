"""Inventaris sumber untuk logbook "Threat Information Feeds" bulanan.

Pure function di atas registry: tidak ada I/O, tidak ada DB. Satu tempat menjawab "scraper ini
membaca URL apa, dengan cara apa", supaya laporan tidak menebak dari nama file."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal
from urllib.parse import urlsplit

from cti_scraper.base import BaseScraper
from cti_scraper.families.api import ApiScraper
from cti_scraper.families.github_commits import GithubCommitWatcher
from cti_scraper.families.rss import RSSScraper
from cti_scraper.families.xpath import XPathScraper

Method = Literal["XML", "Playwright", "Request"]


def source_urls(cls: type[BaseScraper]) -> tuple[str, ...]:
    """URL sumber sebuah scraper, berurutan dari yang paling eksplisit.

    `meta.source_url` menang karena sengaja diisi manusia; sesudahnya family menentukan
    (`feeds` untuk RSS, `url` untuk XPath/API, repo untuk watcher GitHub). Collector bespoke tanpa
    `source_url` mengembalikan `()` -- lebih jujur daripada menebak. Pakai `issubclass` pada kelas
    family, bukan mengintip atribut, supaya atribut kebetulan di collector tidak salah terbaca."""
    if cls.meta.source_url:
        return (cls.meta.source_url,)
    if issubclass(cls, RSSScraper):
        return tuple(cls.feeds)
    if issubclass(cls, XPathScraper | ApiScraper):
        return (cls.url,)
    if issubclass(cls, GithubCommitWatcher):
        return (f"https://github.com/{cls.owner}/{cls.repo}",)
    return ()


def hosts(urls: Iterable[str]) -> tuple[str, ...]:
    """Host unik dari `urls`, urutan kemunculan dipertahankan. `www.` sengaja tidak dibuang:
    logbook lama menuliskan host apa adanya."""
    seen: dict[str, None] = {}
    for url in urls:
        host = urlsplit(url).hostname
        if host:
            seen.setdefault(host)
    return tuple(seen)


def method_for(cls: type[BaseScraper]) -> Method:
    """Cara sumber dibaca, memakai istilah kolom "Method" di logbook: RSS -> XML, scraper yang
    butuh browser -> Playwright, selebihnya (HTML/API/GitHub) -> Request."""
    if issubclass(cls, RSSScraper):
        return "XML"
    if cls.meta.runtime == "browser":
        return "Playwright"
    return "Request"
