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
        routing={"msg_data": f"Tweet : {text}"} if notify else {},
        notice_text=f"<b>{text}</b>" if notify else None,
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
    assert job.context["routing"] == {}
    assert job.context["notify"] is False
    assert job.context["notice_text"] is None
    assert "notice_text" not in job.context["tweet"]
    assert set(job.context) == {"tweet", "scan_results", "routing", "notify", "notice_text"}


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
    # Pesan ikut dari kedatangan `notify=True`: tanpa itu worker tidak punya teks untuk dikirim.
    assert job.context["notice_text"] == "<b>hello</b>"
    assert job.context["routing"] == {"msg_data": "Tweet : hello"}


def test_notify_true_context_survives_a_later_notify_false_arrival(
    session: Session, sent: list[int]
) -> None:
    run(session, tweet("1", notify=True))
    from cti_scraper.base import ScraperMeta

    meta = ScraperMeta(id="other", source="Other", schedule="*/15 * * * *", max_items=5)
    sinks.dispatch(tweet("1", notify=False), meta, session)

    (job,) = jobs(session)
    assert job.context["notify"] is True and job.context["notice_text"] == "<b>hello</b>"


def test_finish_run_send_failure_is_logged_and_other_jobs_still_sent(
    session: Session, sent: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    import structlog

    def flaky(job_id: int) -> None:
        sent.append(job_id)
        if len(sent) == 1:
            raise RuntimeError("broker down")

    monkeypatch.setattr("cti_core.celery_client.send_enrich_llm", flaky)

    with structlog.testing.capture_logs() as logs:
        run(session, tweet("1"), tweet("2"))

    assert len(sent) == 2
    assert [e["job_id"] for e in logs if e["event"] == "tweet_job_send_now_failed"] == sent[:1]


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


def test_job_identity_is_the_tweet_id_not_the_url(session: Session, sent: list[int]) -> None:
    """`monitor_x` (twitterapi) bisa mengirim url kosong: dua tweet berbeda tanpa url tetap dua
    job, bukan satu konflik `(tweet, hash(""))`."""
    a, b = tweet("1"), tweet("2")
    a.url = b.url = ""

    run(session, a, b)

    assert sorted(j.context["tweet"]["tweet_id"] for j in jobs(session)) == ["1", "2"]


def test_same_tweet_with_different_urls_from_two_scrapers_is_one_job(
    session: Session, sent: list[int]
) -> None:
    """X official dan twitterapi membentuk URL berbeda untuk tweet yang sama: tetap satu job, dan
    `notify` di-OR seperti konflik biasa."""
    from cti_scraper.base import ScraperMeta

    run(session, tweet("1", notify=False))
    other = tweet("1", notify=True)
    other.url = "https://twitter.com/A/status/1?s=20"
    meta = ScraperMeta(id="other", source="Other", schedule="*/15 * * * *", max_items=5)
    sinks.dispatch(other, meta, session)

    (job,) = jobs(session)
    assert job.context["notify"] is True and job.context["notice_text"] == "<b>hello</b>"


def test_sink_skips_tweet_that_already_has_a_verdict(session: Session, sent: list[int]) -> None:
    """Tweet yang sudah divonis (mis. ditolak lewat `monitor_x`) tidak diklasifikasi ulang oleh
    scraper lain: tidak ada job baru, tidak ada panggilan LLM kedua."""
    from cti_core.db.repositories.tweet import TweetVerdictRepo

    TweetVerdictRepo(session).record(
        tweet_id="1", text="hello", related_cyber=False, source="llm",
        prompt_version=None, relevance=None,
    )  # fmt: skip

    run(session, tweet("1"))

    assert jobs(session) == []
