"""`load_examples` -- Postgres REAL (testcontainers)."""

from __future__ import annotations

import datetime as dt

from cti_core.db.models.article import Article, RejectedArticle
from cti_enrich.relevance.dataset import load_examples
from sqlalchemy import delete
from sqlalchemy.orm import Session

NOW = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.UTC)


def _art(n: int, news_type: str, **kw: object) -> Article:
    return Article(
        url=f"https://ds.example/a{n}", url_hash=f"ds-a{n}", title=f"Artikel {n}", source="T",
        first_seen_at=NOW, last_seen_at=NOW, seen_count=1, news_type=news_type, **kw,
    )  # fmt: skip


def _rej(n: int, **kw: object) -> RejectedArticle:
    return RejectedArticle(
        url=f"https://ds.example/r{n}", url_hash=f"ds-r{n}", title=f"Ditolak {n}", source="T",
        reason="not cyber", rejected_at=NOW, **kw,
    )  # fmt: skip


def test_load_examples_reads_both_tables(db_session: Session) -> None:
    db_session.execute(delete(Article))
    db_session.execute(delete(RejectedArticle))
    db_session.add_all(
        [
            _art(1, "Ransomware"),
            _art(2, "Security Technology & Best Practices"),
            _rej(1),
            _rej(2, failure_kind="transient"),
        ]
    )
    db_session.flush()

    got = {e.title: e.label for e in load_examples(db_session)}
    assert got == {
        "Artikel 1": "threat_news",
        "Artikel 2": "best_practice",
        "Ditolak 1": "reject",
    }
