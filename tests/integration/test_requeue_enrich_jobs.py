"""`tools/ops/requeue_enrich_jobs.py` di Postgres beneran: laporan tidak menulis, apply memindahkan
job classify ke `rejected_articles` (transient) dan menghapus job ttp, ulang = no-op."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cti_core.db.models.article import Article
from sqlalchemy import text
from sqlalchemy.orm import Session

from tools.ops import requeue_enrich_jobs as tool


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


def _seed(s: Session) -> None:
    s.execute(text("DELETE FROM enrich_jobs"))
    s.execute(text("DELETE FROM rejected_articles"))
    for i, (kind, state) in enumerate([("classify", "pending"), ("classify", "failed")]):
        s.execute(
            text(
                """
                INSERT INTO enrich_jobs (kind, url, url_hash, title, source, state, last_error)
                VALUES (:k, :u, :h, 'T', 'src', :s, 'boom')
                """
            ),
            {"k": kind, "u": f"https://rq.test/{i}", "h": f"{i}" * 64, "s": state},
        )
    s.flush()


def _ttp_job(s: Session) -> None:
    art = Article(url="https://rq.test/art", url_hash="r" * 64, title="A", source="src")
    s.add(art)
    s.flush()
    s.execute(
        text(
            """
            INSERT INTO enrich_jobs (kind, url, url_hash, title, source, article_id)
            VALUES ('ttp', :u, :h, 'T', 'src', :a)
            """
        ),
        {"u": art.url, "h": art.url_hash, "a": art.id},
    )
    s.flush()


def _counts(s: Session) -> tuple[int, int, int]:
    jobs = s.execute(text("SELECT count(*) FROM enrich_jobs WHERE kind='classify'")).scalar_one()
    ttp = s.execute(text("SELECT count(*) FROM enrich_jobs WHERE kind='ttp'")).scalar_one()
    rej = s.execute(
        text("SELECT count(*) FROM rejected_articles WHERE failure_kind='transient'")
    ).scalar_one()
    return jobs, ttp, rej


def test_report_writes_nothing(session: Session) -> None:
    _seed(session)
    summary = tool.count(session)
    assert (summary.classify_pending, summary.classify_failed) == (1, 1)
    assert _counts(session) == (2, 0, 0)


def test_apply_moves_classify_drops_ttp_and_rerun_is_noop(session: Session) -> None:
    _seed(session)
    _ttp_job(session)
    assert _counts(session)[:2] == (2, 1)
    summary = tool.requeue(session)
    assert (summary.classify_pending, summary.classify_failed, summary.ttp) == (1, 1, 1)
    assert _counts(session) == (0, 0, 2)
    row = session.execute(
        text(
            "SELECT reason, auto_replay_count FROM rejected_articles "
            "WHERE failure_kind='transient' LIMIT 1"
        )
    ).one()
    assert row.reason == tool.REASON and row.auto_replay_count == 0
    again = tool.requeue(session)
    assert (again.classify_pending, again.classify_failed, again.ttp) == (0, 0, 0)
    assert _counts(session) == (0, 0, 2)
