"""Kontrak inventaris sumber untuk logbook "Threat Information Feeds" bulanan.

Setiap scraper wajib menyebut kapan sumbernya masuk platform (`meta.added`, kolom "Added Date")
dan harus bisa diselesaikan ke minimal satu URL sumber absolut (kolom "Domain"/"Source Link").
Tanpa test ini scraper baru gampang lupa `added`, dan laporan bulanan yang ditandatangani akan
punya baris kosong.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlparse

from cti_scraper import registry
from cti_scraper.inventory import source_urls


def _real_scrapers() -> dict[str, type]:
    """Hanya scraper paket `cti_scrapers` -- test lain mendaftarkan scraper palsu ke registry
    yang sama dan itu bukan urusan kontrak ini (pola sama dengan `test_scraper_content_kind`)."""
    return {
        sid: cls
        for sid, cls in registry.discover().items()
        if cls.__module__.startswith("cti_scrapers.")
    }


def test_every_scraper_declares_when_it_was_added() -> None:
    assert {s for s, c in _real_scrapers().items() if not isinstance(c.meta.added, date)} == set()


def test_added_dates_are_not_in_the_future() -> None:
    today = date.today()
    assert {
        s: c.meta.added
        for s, c in _real_scrapers().items()
        if c.meta.added and c.meta.added > today
    } == {}


def test_every_scraper_resolves_an_absolute_source_url() -> None:
    def absolute(url: str) -> bool:
        parts = urlparse(url)
        return parts.scheme in ("http", "https") and bool(parts.netloc)

    bad = {
        s
        for s, c in _real_scrapers().items()
        if not source_urls(c) or not all(absolute(u) for u in source_urls(c))
    }
    assert bad == set()
