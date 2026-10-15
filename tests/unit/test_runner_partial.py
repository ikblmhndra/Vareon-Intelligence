"""`ScrapeContext.mark_partial()` -> `Runner` mencatat status `partial`, bukan `ok`.

Dipakai `new_cve` saat `max_items` memotong run (lihat `test_new_cve_max_items`). `partial` sudah
dikenali DB (`ScraperRun.status`), `/cve/freshness` (`SUCCESS_STATUSES`) dan badge UI Scrapers,
tapi dulu tak ada yang pernah mengeluarkannya."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.items import Item
from cti_scraper.runner import Runner


def make_scraper(fetch: Callable[[ScrapeContext], Iterator[Item]]) -> type[BaseScraper]:
    # `__abstract__` -> `__init_subclass__` tidak menyelipkan scraper palsu ke registry global
    # (contract test iterasi registry), pola yang sama dengan `tests/integration/test_runner.py`.
    class _Scraper(BaseScraper):
        __abstract__ = True
        meta = ScraperMeta(id="dummy_partial", source="Dummy", schedule="0 * * * *")

        def fetch(self, ctx: ScrapeContext) -> Iterator[Item]:
            return fetch(ctx)

    return _Scraper


def marks_then_ends(ctx: ScrapeContext) -> Iterator[Item]:
    ctx.mark_partial("kena batas")
    return iter(())


def marks_after_the_loop(ctx: ScrapeContext) -> Iterator[Item]:
    yield from ()
    ctx.mark_partial("kena batas")


def completes(ctx: ScrapeContext) -> Iterator[Item]:
    return iter(())


def marks_then_crashes(ctx: ScrapeContext) -> Iterator[Item]:
    ctx.mark_partial("kena batas")
    raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from cti_core.config import get_settings

    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_a_scraper_that_marks_the_run_partial_ends_with_status_partial() -> None:
    result = Runner(make_scraper(marks_then_ends), dry_run=True).execute(trigger="manual")

    assert result.status == "partial"
    assert result.errors == [{"stage": "fetch", "type": "Partial", "message": "kena batas"}]


def test_the_partial_mark_is_read_after_the_generator_is_exhausted() -> None:
    result = Runner(make_scraper(marks_after_the_loop), dry_run=True).execute(trigger="manual")

    assert result.status == "partial"


def test_a_run_nobody_marked_partial_stays_empty_or_ok() -> None:
    result = Runner(make_scraper(completes), dry_run=True).execute(trigger="manual")

    assert result.status == "empty"  # nol item, tidak ditandai terpotong
    assert result.errors == []


def test_a_real_error_wins_over_the_partial_mark() -> None:
    result = Runner(make_scraper(marks_then_crashes), dry_run=True).execute(trigger="manual")

    assert result.status == "fetch_error"
