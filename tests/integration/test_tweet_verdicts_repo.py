"""TweetVerdictRepo: record idempoten per tweet, llm_rows hanya sumber LLM, purge lintas sumber."""

from __future__ import annotations

import datetime

from cti_core.db.models.tweet_verdict import TweetVerdict
from cti_core.db.repositories.tweet import TweetVerdictRepo
from sqlalchemy import select, update
from sqlalchemy.orm import Session

NOW = datetime.datetime(2026, 11, 16, 12, 0, tzinfo=datetime.UTC)


def _record(repo: TweetVerdictRepo, tweet_id: str, source: str = "llm", **kw) -> None:  # type: ignore[no-untyped-def]
    repo.record(
        tweet_id=tweet_id,
        text=kw.pop("text", "teks"),
        related_cyber=kw.pop("related_cyber", True),
        source=source,
        prompt_version=kw.pop("prompt_version", "v1"),
        relevance=kw.pop("relevance", {"relevance_score": 0.9}),
    )


def test_record_is_idempotent_per_tweet(db_session: Session) -> None:
    repo = TweetVerdictRepo(db_session)
    _record(repo, "1", related_cyber=True)
    _record(repo, "1", related_cyber=False, text="beda")
    rows = db_session.execute(select(TweetVerdict)).scalars().all()
    assert len(rows) == 1
    assert rows[0].related_cyber is True
    assert rows[0].text == "teks"


def test_llm_rows_exclude_gate_rows(db_session: Session) -> None:
    repo = TweetVerdictRepo(db_session)
    _record(repo, "1", "llm")
    _record(repo, "2", "gate", prompt_version=None, relevance=None, related_cyber=False)
    _record(repo, "3", "llm")
    db_session.flush()
    db_session.execute(
        update(TweetVerdict)
        .where(TweetVerdict.tweet_id == "1")
        .values(created_at=NOW - datetime.timedelta(days=2))
    )
    db_session.execute(
        update(TweetVerdict).where(TweetVerdict.tweet_id == "3").values(created_at=NOW)
    )
    got = repo.llm_rows()
    assert [r.tweet_id for r in got] == ["3", "1"]  # terbaru dulu
    since = repo.llm_rows(since=NOW - datetime.timedelta(days=1))
    assert [r.tweet_id for r in since] == ["3"]


def test_purge_deletes_rows_older_than_cutoff_regardless_of_source(db_session: Session) -> None:
    repo = TweetVerdictRepo(db_session)
    _record(repo, "old-llm", "llm")
    _record(repo, "old-gate", "gate", prompt_version=None, relevance=None)
    _record(repo, "new", "llm")
    db_session.flush()
    old = NOW - datetime.timedelta(days=100)
    db_session.execute(
        update(TweetVerdict)
        .where(TweetVerdict.tweet_id.in_(["old-llm", "old-gate"]))
        .values(created_at=old)
    )
    assert repo.purge(NOW - datetime.timedelta(days=90)) == 2
    left = db_session.execute(select(TweetVerdict.tweet_id)).scalars().all()
    assert left == ["new"]
