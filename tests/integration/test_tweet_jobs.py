"""Job `tweet` di job runner (`cti_enrich.jobs.run_job` -> `cti_enrich.tweet_job`) terhadap Postgres
REAL (spec tweet-llm-cost, Part A "Worker"). LLM (`classify_tweet`) dan Telegram (`send_alert`)
di-patch; routing (`route_tweet`), `tweets`, `tweet_verdicts` dan pencatatan kegagalan asli.

Menggantikan test scraper yang dihapus Task 6 (routing topik, kolom arsip, kegagalan LLM/kuota):
klasifikasi dan notice sekarang terjadi di worker, bukan di `fetch()`."""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import openai
import pytest
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.models.tweet import Tweet
from cti_core.db.models.tweet_verdict import TweetVerdict
from cti_core.db.repositories.enrich_job import EnrichJobRepo
from cti_enrich import jobs, tweet_job
from cti_enrich.stages.classify import TWEET_PROMPT_VERSION, ClassifyResult, OpenAIQuotaExhausted
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

NOW = datetime.datetime(2026, 11, 17, 12, 0, tzinfo=datetime.UTC)
NOTICE = "<b>NEW TWEET</b> notice"
VERDICT = ClassifyResult(
    related_cyber=True,
    confidence=0.87,
    industries_impacted=["Energy"],
    victim_countries=["Indonesia"],
    actor_countries=["Russia"],
    confirmed_incident=True,
    incident_confidence=0.64,
    incident_indicators=["encrypted systems"],
    victim_name="Acme Power",
    audit={"model": "stub", "prompt_version": TWEET_PROMPT_VERSION},
)
REJECT = ClassifyResult(related_cyber=False, confidence=0.9)
_REQ = httpx.Request("POST", "http://gw/v1/chat/completions")


@pytest.fixture
def session(_migrated_schema: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    s.execute(delete(EnrichJob))

    @contextmanager
    def _shared() -> Iterator[Session]:
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise

    monkeypatch.setattr(jobs, "sync_session", _shared)
    monkeypatch.setattr(tweet_job, "sync_session", _shared)
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(tweet_job, "send_alert", lambda topic, text: calls.append((topic, text)))
    return calls


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`classify_tweet` palsu: vonis `VERDICT`; teks yang diklasifikasi dicatat."""
    seen: list[str] = []

    def fake(text: str) -> ClassifyResult:
        seen.append(text)
        return VERDICT

    monkeypatch.setattr(tweet_job, "classify_tweet", fake)
    return seen


def routing(msg_data: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "msg_data": msg_data,
        "cve_list": [],
        "related_tech_status": False,
        "report_status": False,
        "ot_status": False,
        "databreach_list": [],
        "zero_day_list": [],
    }
    return {**base, **over}


def make_job(
    session: Session,
    *,
    tweet_id: str = "1001",
    text: str = "Attack on critical infrastructure today",
    author: str = "blackorbird",
    posted: datetime.datetime | None = NOW - datetime.timedelta(minutes=30),
    notify: bool = True,
    route: dict[str, Any] | None = None,
    notice_text: str | None = NOTICE,
) -> int:
    url = f"https://x.com/{author or 'i'}/status/{tweet_id}"
    job = EnrichJobRepo(session).create_tweet(
        url=url,
        title=text[:300],
        source="Twitter Alerts",
        scraper_id="tweet_alerts_1h",
        posted_on=posted.date() if posted else None,
        input_text=text,
        context={
            "tweet": {
                "tweet_id": tweet_id,
                "url": url,
                "text": text,
                "author_username": author,
                "author_name": "Black Orbird",
                "author_avatar": "https://pbs.example/a.jpg",
                "author_followers": 1234,
                "posted_on": posted.isoformat().replace("+00:00", "Z") if posted else None,
                "lang": "en",
                "media_urls": ["https://pbs.example/m.jpg"],
            },
            "scan_results": {"cve_list": [], "ot_status": False},
            "routing": route if route is not None else routing(f"Tweet : {text}"),
            "notify": notify,
            "notice_text": notice_text,
        },
    )
    assert job is not None
    session.commit()
    return job.id


def stored(session: Session, tweet_id: str = "1001") -> Tweet | None:
    return session.scalar(select(Tweet).where(Tweet.tweet_id == tweet_id))


def verdict(session: Session, tweet_id: str = "1001") -> TweetVerdict | None:
    return session.scalar(select(TweetVerdict).where(TweetVerdict.tweet_id == tweet_id))


def job_row(session: Session, job_id: int) -> EnrichJob | None:
    return session.get(EnrichJob, job_id, populate_existing=True)


# ── jalur sukses ───────────────────────────────────────────────────────────────────────────


def test_related_tweet_is_stored_and_notified_per_topic(
    session: Session, sent: list[tuple[str, str]], llm: list[str]
) -> None:
    job_id = make_job(session)

    assert jobs.run_job(job_id, now=NOW) == "done"

    assert llm == ["Attack on critical infrastructure today"]
    # Kata kunci OT di teks pesan -> `ot` DAN topik generik (perilaku lama `_sendAlert`).
    assert sent == [("ot", NOTICE), ("feed_twitter", NOTICE)]
    row = stored(session)
    assert row is not None and row.source == "tweet_alerts_1h"
    v = verdict(session)
    assert v is not None and (v.related_cyber, v.source) == (True, "llm")
    assert v.prompt_version == TWEET_PROMPT_VERSION
    assert job_row(session, job_id) is None


def test_archive_row_carries_tweet_scan_and_llm_fields(
    session: Session, sent: list[tuple[str, str]], llm: list[str]
) -> None:
    job_id = make_job(session)

    jobs.run_job(job_id, now=NOW)

    row = stored(session)
    assert row is not None
    assert (row.url, row.text, row.author_username) == (
        "https://x.com/blackorbird/status/1001",
        "Attack on critical infrastructure today",
        "blackorbird",
    )
    assert (row.author_name, row.author_avatar, row.author_followers) == (
        "Black Orbird",
        "https://pbs.example/a.jpg",
        1234,
    )
    assert row.posted_on == NOW - datetime.timedelta(minutes=30)
    assert (row.lang, row.media_urls) == ("en", ["https://pbs.example/m.jpg"])
    assert row.scan_results == {"cve_list": [], "ot_status": False}
    assert row.confidence_score == 87
    assert row.confirmed_incident is True
    assert row.industries_impacted == ["Energy"]
    assert (row.victim_countries, row.actor_countries) == (["Indonesia"], ["Russia"])
    assert row.victim_name == "Acme Power"
    assert row.incident_confidence == 64
    assert row.incident_indicators == ["encrypted systems"]


@pytest.mark.parametrize(
    ("text", "topics"),
    [
        # Penanda di `msg_data` (pesan utuh), bukan sinyal scan: butuh teks dari scraper.
        ("Fresh analysis #threatreport on a loader", ["vendor_report"]),
        ("New claim on the shame-site for #ransomware: acme", []),
        ("New hacktivist alliance announced", ["feed_twitter"]),
    ],
)
def test_topics_that_read_msg_data_route_from_the_stored_message(
    session: Session,
    sent: list[tuple[str, str]],
    llm: list[str],
    text: str,
    topics: list[str],
) -> None:
    job_id = make_job(session, text=text, route=routing(f"<b>Tweet</b> : {text}"))

    assert jobs.run_job(job_id, now=NOW) == "done"

    assert [t for t, _ in sent] == topics
    assert stored(session) is not None


def test_scan_signals_route_before_message_keywords(
    session: Session, sent: list[tuple[str, str]], llm: list[str]
) -> None:
    job_id = make_job(session, route=routing("Tweet : hi", zero_day_list=["0-day"]))

    jobs.run_job(job_id, now=NOW)

    assert sent == [("zero_day", NOTICE)]


def test_unrelated_tweet_is_recorded_but_not_stored(
    session: Session, sent: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tweet_job, "classify_tweet", lambda text: REJECT)
    job_id = make_job(session)

    assert jobs.run_job(job_id, now=NOW) == "done"

    assert stored(session) is None and sent == []
    v = verdict(session)
    assert v is not None and v.related_cyber is False and v.source == "llm"
    assert v.text == "Attack on critical infrastructure today"
    assert job_row(session, job_id) is None


def test_stale_tweet_is_stored_without_notice(
    session: Session, sent: list[tuple[str, str]], llm: list[str]
) -> None:
    job_id = make_job(session, posted=NOW - datetime.timedelta(hours=7))

    assert jobs.run_job(job_id, now=NOW) == "done"

    assert stored(session) is not None and sent == []


def test_tweet_just_inside_the_freshness_limit_is_notified(
    session: Session, sent: list[tuple[str, str]], llm: list[str]
) -> None:
    job_id = make_job(session, posted=NOW - tweet_job.TWEET_ALERT_MAX_AGE)

    jobs.run_job(job_id, now=NOW)

    assert sent


def test_notify_false_stores_without_notice(
    session: Session, sent: list[tuple[str, str]], llm: list[str]
) -> None:
    job_id = make_job(session, notify=False, route={}, notice_text=None)

    assert jobs.run_job(job_id, now=NOW) == "done"

    assert stored(session) is not None and sent == []


def test_empty_author_is_notified_but_not_archived(
    session: Session, sent: list[tuple[str, str]], llm: list[str]
) -> None:
    """Perilaku lama: tweet tanpa `author_username` di-alert tapi tidak masuk `tweets`
    (kolomnya NOT NULL)."""
    job_id = make_job(session, author="")

    assert jobs.run_job(job_id, now=NOW) == "done"

    assert stored(session) is None
    assert [t for t, _ in sent] == ["ot", "feed_twitter"]
    assert verdict(session) is not None
    assert job_row(session, job_id) is None


def test_one_failing_topic_does_not_stop_the_others(
    session: Session, llm: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def flaky(topic: str, text: str) -> None:
        calls.append(topic)
        if topic == "ot":
            raise RuntimeError("telegram down")

    monkeypatch.setattr(tweet_job, "send_alert", flaky)
    job_id = make_job(session)

    assert jobs.run_job(job_id, now=NOW) == "done"

    assert calls == ["ot", "feed_twitter"]
    assert stored(session) is not None  # kegagalan kirim tidak membatalkan tweet tersimpan


def test_already_stored_tweet_is_a_duplicate_without_llm(
    session: Session, sent: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from cti_core.db.repositories.tweet import TweetRepo

    def no_llm(text: str) -> ClassifyResult:
        raise AssertionError("LLM tidak boleh dipanggil")

    monkeypatch.setattr(tweet_job, "classify_tweet", no_llm)
    job_id = make_job(session)
    TweetRepo(session).insert(
        tweet_id="1001", url="https://x.com/a/status/1001", text="t", author_username="a"
    )
    session.commit()

    assert jobs.run_job(job_id, now=NOW) == "duplicate"

    assert job_row(session, job_id) is None and sent == [] and verdict(session) is None


def test_verdict_hook_skips_the_llm_and_records_its_source(
    session: Session, sent: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_llm(text: str) -> ClassifyResult:
        raise AssertionError("LLM tidak boleh dipanggil")

    monkeypatch.setattr(tweet_job, "classify_tweet", no_llm)
    job_id = make_job(session)

    outcome = tweet_job.run_tweet_job(
        job_id, NOW, verdict_for=lambda s, job: (VERDICT, "gate", {"p": 0.99})
    )

    assert outcome == "done"
    v = verdict(session)
    assert v is not None and (v.source, v.relevance, v.prompt_version) == (
        "gate",
        {"p": 0.99},
        None,
    )
    assert stored(session) is not None and sent


# ── job hilang ─────────────────────────────────────────────────────────────────────────────


def test_missing_job_is_gone(session: Session, sent: list[tuple[str, str]], llm: list[str]) -> None:
    """Sink bisa mengirim id baris yang ikut di-rollback (Carry-forward D)."""
    assert jobs.run_job(987_654_321, now=NOW) == "gone"
    assert tweet_job.run_tweet_job(987_654_321, NOW) == "gone"
    assert llm == [] and sent == []


def test_analyst_decision_is_not_allowed_for_tweet_jobs(
    session: Session, sent: list[tuple[str, str]], llm: list[str]
) -> None:
    job_id = make_job(session)

    with pytest.raises(jobs.DecisionNotAllowed):
        jobs.run_job(job_id, decision="accept", now=NOW)

    job = job_row(session, job_id)
    assert job is not None and job.state == "pending"


# ── kegagalan LLM ──────────────────────────────────────────────────────────────────────────


def test_gateway_error_reschedules_and_stores_nothing(
    session: Session, sent: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = [0]

    def flaky(text: str) -> ClassifyResult:
        calls[0] += 1
        if calls[0] == 1:
            raise openai.InternalServerError(
                "upstream down", response=httpx.Response(503, request=_REQ), body=None
            )
        return VERDICT

    monkeypatch.setattr(tweet_job, "classify_tweet", flaky)
    job_id = make_job(session)

    assert jobs.run_job(job_id, now=NOW) == "retry"

    assert stored(session) is None and verdict(session) is None and sent == []
    job = job_row(session, job_id)
    assert job is not None and (job.state, job.attempts) == ("pending", 1)
    assert job.next_attempt_at == NOW + datetime.timedelta(minutes=2)

    assert jobs.run_job(job_id, now=NOW) == "done"
    assert stored(session) is not None and verdict(session) is not None
    assert job_row(session, job_id) is None


def test_quota_exhausted_is_a_gateway_error(
    session: Session, sent: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    failed: list[tuple[str, str]] = []

    def broke(text: str) -> ClassifyResult:
        raise OpenAIQuotaExhausted("insufficient_funds")

    monkeypatch.setattr(tweet_job, "classify_tweet", broke)
    job_id = make_job(session)

    assert jobs.run_job(job_id, now=NOW, on_failed=lambda *a: failed.append(a)) == "retry"

    job = job_row(session, job_id)
    assert job is not None and (job.state, job.attempts) == ("pending", 1)
    assert job.last_error is not None and job.last_error.startswith("OpenAIQuotaExhausted")
    assert failed == [] and stored(session) is None and verdict(session) is None


def test_json_errors_fail_the_job_after_three(
    session: Session, sent: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    failed: list[tuple[str, str]] = []

    def broken(text: str) -> ClassifyResult:
        raise json.JSONDecodeError("Expecting value", "<think>", 0)

    monkeypatch.setattr(tweet_job, "classify_tweet", broken)
    job_id = make_job(session)

    outcomes = [
        jobs.run_job(job_id, now=NOW, on_failed=lambda *a: failed.append(a)) for _ in range(3)
    ]

    assert outcomes == ["retry", "retry", "failed"]
    job = job_row(session, job_id)
    assert job is not None and (job.state, job.json_failures) == ("failed", 3)
    assert len(failed) == 1 and failed[0][0] == "Attack on critical infrastructure today"
    # Job `failed` menunggu analis: kiriman basi dispatcher tidak memanggil LLM lagi.
    assert jobs.run_job(job_id, now=NOW) == "failed"
    assert stored(session) is None and verdict(session) is None and sent == []
