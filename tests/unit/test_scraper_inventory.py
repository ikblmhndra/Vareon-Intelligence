"""`cti_scraper.inventory`: URL, host dan method sebuah scraper untuk logbook feed bulanan."""

from __future__ import annotations

from collections.abc import Iterator

from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.families.xpath import XPathScraper
from cti_scraper.inventory import hosts, method_for, source_urls
from cti_scraper.items import Item
from cti_scraper.registry import discover


def test_rss_lists_every_feed_and_reads_as_xml():
    cls = discover()["anyrun"]
    assert source_urls(cls) == ("https://any.run/cybersecurity-blog/feed/",)
    assert method_for(cls) == "XML"


def test_browser_xpath_reads_as_playwright():
    cls = discover()["abnormalsecurity"]
    assert source_urls(cls) == ("https://abnormal.ai/blog?filter=threat-intel",)
    assert method_for(cls) == "Playwright"


def test_github_watcher_points_at_the_repo():
    cls = discover()["mitre_github"]
    assert source_urls(cls) == ("https://github.com/mitre-attack/attack-stix-data",)
    assert method_for(cls) == "Request"


def _bare(source_url: str | None) -> type[BaseScraper]:
    # `__abstract__` -> tidak masuk registry global (pola tests/unit/test_runner_partial.py).
    class _Bare(BaseScraper):
        __abstract__ = True
        meta = ScraperMeta(
            id="dummy_inv", source="Dummy", schedule="0 * * * *", source_url=source_url
        )

        def fetch(self, ctx: ScrapeContext) -> Iterator[Item]:
            return iter(())

    return _Bare


def test_explicit_source_url_wins_and_a_bare_collector_without_one_resolves_nothing():
    with_url = _bare("https://x.com")
    assert source_urls(with_url) == ("https://x.com",)
    assert method_for(with_url) == "Request"
    assert source_urls(_bare(None)) == ()

    class _Xp(XPathScraper):
        __abstract__ = True
        meta = ScraperMeta(
            id="dummy_inv_xp",
            source="DummyXp",
            schedule="0 * * * *",
            source_url="https://b.example",
        )
        url = "https://a.example/list"

    assert source_urls(_Xp) == ("https://b.example",)


def test_hosts_are_unique_in_order_and_keep_www():
    urls = ["https://www.a.com/x", "https://b.com/y", "https://www.a.com/z"]
    assert hosts(urls) == ("www.a.com", "b.com")
