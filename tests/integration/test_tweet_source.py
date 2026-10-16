"""`tweets.source` -- Postgres REAL (testcontainers).

`tweet_alerts_*` ikut menulis `tweets` (2026-10-16), dan `monitor_x` memakai MAX(`tweet_id`)
per akun sebagai `since_id`. Yang dijaga di sini: (1) sink mencatat scraper penulisnya, (2) tweet
yang sudah disimpan scraper lain tidak ditimpa, (3) baris jalur alert TIDAK menggeser `since_id`
`monitor_x` (kalau menggeser, tweet yang ditolak filter alert tidak pernah terambil `monitor_x`).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cti_core.db.models.tweet import Tweet
from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.items import TweetItem
from cti_scraper.reference_data import _resolve_tweet_last_seen_ids
from cti_scraper.runner import Runner
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.fixture
def session(_migrated_schema: None) -> Iterator[Session]:
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


def make_scraper(scraper_id: str, *items: TweetItem) -> type[BaseScraper]:
    class _Scraper(BaseScraper):
        __abstract__ = True
        meta = ScraperMeta(id=scraper_id, source="Test", schedule="*/15 * * * *", max_items=50)

        def fetch(self, ctx: ScrapeContext) -> Iterator[TweetItem]:
            yield from items

    return _Scraper


def tweet_item(tweet_id: str, author: str = "FalconFeedsio", text: str = "x") -> TweetItem:
    return TweetItem(
        tweet_id=tweet_id,
        url=f"https://x.com/{author}/status/{tweet_id}",
        text=text,
        author_username=author,
    )


def test_the_sink_records_the_scraper_that_wrote_the_tweet(session: Session) -> None:
    scraper = make_scraper("test-alerts", tweet_item("100"))

    result = Runner(scraper, session=session, cold_start_max_items=99).execute()

    assert result.items_new == 1
    assert session.scalars(select(Tweet.source).where(Tweet.tweet_id == "100")).one() == (
        "test-alerts"
    )


def test_a_tweet_already_stored_by_another_scraper_is_kept_untouched(session: Session) -> None:
    first = make_scraper("test-monitor", tweet_item("100", text="versi monitor"))
    second = make_scraper("test-alerts", tweet_item("100", text="versi alert"))

    Runner(first, session=session, cold_start_max_items=99).execute()
    Runner(second, session=session, cold_start_max_items=99).execute()

    row = session.scalars(select(Tweet).where(Tweet.tweet_id == "100")).one()
    assert (row.source, row.text) == ("test-monitor", "versi monitor")


def test_a_tweet_without_an_explicit_source_defaults_to_monitor_x(session: Session) -> None:
    session.add(Tweet(tweet_id="1", url="u", text="t", author_username="a"))
    session.flush()

    assert session.scalars(select(Tweet.source).where(Tweet.tweet_id == "1")).one() == "monitor_x"


def test_since_id_ignores_tweets_written_by_the_alert_scrapers(session: Session) -> None:
    def add(tweet_id: str, author: str, source: str) -> None:
        session.add(
            Tweet(tweet_id=tweet_id, url="u", text="t", author_username=author, source=source)
        )

    add("100", "FalconFeedsio", "monitor_x")
    add("200", "FalconFeedsio", "tweet_alerts_1h")  # lebih baru, tapi dari jalur alert
    add("300", "rst_cloud", "tweet_alerts_30m")  # akun yang cuma pernah di-alert
    session.flush()

    assert _resolve_tweet_last_seen_ids(session) == {"falconfeedsio": "100"}
