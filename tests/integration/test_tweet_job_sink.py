"""`TweetJobItem` -> job `tweet` di `enrich_jobs` lewat `Runner` (persist-first, tanpa LLM)."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.repositories.tweet import TweetRepo
from cti_scraper import sinks
from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.items import Item, TweetJobItem
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

SID = "test-tweet-job"


@pytest.fixture
def session(_migrated_schema: None) -> Iterator[Session]:
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    s.execute(delete(EnrichJob))
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(
        "cti_core.celery_client.send_enrich_llm", lambda job_id: calls.append(job_id)
    )
    monkeypatch.setattr(
        "cti_core.db.repositories.enrich_job.lease_if_closed", lambda session, job: True
    )
    return calls


def make_scraper(feed: Callable[[], list[Item]]) -> type[BaseScraper]:
    class _Scraper(BaseScraper):
        __abstract__ = True
        meta = ScraperMeta(id=SID, source="Test", schedule="*/15 * * * *", max_items=50)

        def fetch(self, ctx: ScrapeContext) -> Iterator[Item]:
            yield from feed()

    return _Scraper


def tweet(tweet_id: str = "1", *, notify: bool = False, text: str = "hello") -> TweetJobItem:
    return TweetJobItem(
        tweet_id=tweet_id,
        url=f"https://x.com/a/status/{tweet_id}",
        text=text,
        author_username="a",
        scan_results={"cve_list": []},
        routing={"topic": "apt"},
        notify=notify,
    )


def run(session: Session, *items: TweetJobItem) -> None:
    from cti_scraper.runner import Runner

    Runner(make_scraper(lambda: list(items)), session=session, cold_start_max_items=99).execute()


def jobs(session: Session) -> list[EnrichJob]:
    return list(session.scalars(select(EnrichJob).where(EnrichJob.kind == "tweet")))


def test_sink_creates_one_tweet_job(session: Session, sent: list[int]) -> None:
    long_text = "x" * 400

    run(session, tweet(text=long_text))

    (job,) = jobs(session)
    assert job.title == long_text[:300] and job.input_text == long_text
    assert job.scraper_id == SID
    assert job.context["tweet"]["tweet_id"] == "1"
    assert job.context["scan_results"] == {"cve_list": []}
    assert job.context["routing"] == {"topic": "apt"}
    assert job.context["notify"] is False


def test_sink_skips_tweet_already_stored(session: Session, sent: list[int]) -> None:
    TweetRepo(session).insert(
        tweet_id="1", url="https://x.com/a/status/1", text="hello", author_username="a"
    )

    run(session, tweet("1"))

    assert jobs(session) == []


def test_notify_is_ored_on_conflict(session: Session, sent: list[int]) -> None:
    run(session, tweet("1", notify=False))
    # Dedup scraper_seen mencegah item yang sama di run kedua; panggil sink langsung.
    from cti_scraper.base import ScraperMeta

    meta = ScraperMeta(id="other", source="Other", schedule="*/15 * * * *", max_items=5)
    sinks.dispatch(tweet("1", notify=True), meta, session)
    sinks.dispatch(tweet("1", notify=False), meta, session)

    (job,) = jobs(session)
    assert job.context["notify"] is True


def test_sink_ignores_enrich_backpressure(
    session: Session, sent: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise AssertionError("tweet job tidak boleh kena backpressure")

    monkeypatch.setattr(sinks, "ensure_enrich_capacity", boom)
    monkeypatch.setattr(sinks, "_enrich_queue_depth", lambda: 10**9)

    run(session, tweet("1"))

    assert len(jobs(session)) == 1


def test_sink_sends_enrich_llm_when_breaker_closed(session: Session, sent: list[int]) -> None:
    run(session, tweet("1"))

    (job,) = jobs(session)
    assert sent == [job.id]


def test_sink_does_not_send_when_breaker_open(
    session: Session, sent: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cti_core.db.repositories.enrich_job.lease_if_closed", lambda session, job: False
    )

    run(session, tweet("1"))

    assert len(jobs(session)) == 1 and sent == []
