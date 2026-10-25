"""`cti_enrich.backfill_tier1` di Postgres beneran: add-only, dry-run tidak menulis, gagal fetch
dihitung dan dilewati, `--since`/`--limit` membatasi pindai. `fetch` diganti fungsi palsu."""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import pytest
from cti_core.db.models.article import Article
from cti_core.db.models.threat_reference import ThreatActorGroup
from cti_core.db.repositories.article import ArticleRepo
from cti_enrich.backfill_tier1 import backfill_tier1
from sqlalchemy.orm import Session

TEXT = "Kimsuky operators deployed their tooling against research staff."


@pytest.fixture
def session(_migrated_schema: None) -> Iterator[Session]:
    """`create_savepoint`: commit/rollback per artikel milik backfill hanya menyentuh SAVEPOINT,
    transaksi luar di-rollback saat teardown."""
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


def _add(session: Session, n: int, posted: datetime.date | None = None, **kw: object) -> Article:
    art = ArticleRepo(session).upsert(
        url=f"https://example.com/bf-tier1-{n}", title=f"Kimsuky story {n}", source="s", **kw
    )
    art.posted_on = posted
    return art


def _fetch(url: str) -> str:
    return TEXT


@pytest.fixture
def seeded(session: Session) -> Session:
    session.add(ThreatActorGroup(name="kimsuky", source="manual"))
    session.flush()
    return session


def _actors(session: Session, art: Article) -> list[str]:
    session.refresh(art)
    return sorted(a.threat_actor for a in art.threat_actors)


def test_dry_run_writes_nothing(seeded: Session) -> None:
    art = _add(seeded, 1)
    seeded.commit()

    stats = backfill_tier1(seeded, since=None, limit=None, sleep=0, dry_run=True, fetch=_fetch)

    assert stats.scanned >= 1
    assert stats.actor_rows_added == 1
    assert _actors(seeded, art) == []


def test_adds_only_missing_rows(seeded: Session) -> None:
    art = _add(seeded, 2)
    ArticleRepo(seeded).set_enrichment(art, threat_actors=["Apt29"], industries=["Finance"])
    seeded.commit()

    stats = backfill_tier1(seeded, since=None, limit=None, sleep=0, dry_run=False, fetch=_fetch)

    assert stats.actor_rows_added == 1
    assert _actors(seeded, art) == ["Apt29", "Kimsuky"]
    assert [i.industry for i in art.industries] == ["Finance"]  # industri LLM tidak ditimpa
    # idempoten: jalan kedua tidak menambah apa pun
    again = backfill_tier1(seeded, since=None, limit=None, sleep=0, dry_run=False, fetch=_fetch)
    assert again.actor_rows_added == 0


def test_best_practice_gets_no_actors(seeded: Session) -> None:
    art = _add(seeded, 3, news_type="Security Technology & Best Practices")
    seeded.commit()

    stats = backfill_tier1(seeded, since=None, limit=None, sleep=0, dry_run=False, fetch=_fetch)

    assert stats.actor_rows_added == 0
    assert _actors(seeded, art) == []


def test_fetch_failure_counted_and_skipped(seeded: Session) -> None:
    ok = _add(seeded, 4)
    bad = _add(seeded, 5)
    seeded.commit()

    def flaky(url: str) -> str:
        if url.endswith("-5"):
            raise RuntimeError("boom")
        return TEXT

    stats = backfill_tier1(seeded, since=None, limit=None, sleep=0, dry_run=False, fetch=flaky)

    assert stats.fetch_failed == 1
    assert stats.fetched == stats.scanned - 1
    assert _actors(seeded, ok) == ["Kimsuky"]
    assert _actors(seeded, bad) == []


def test_empty_text_counts_as_fetch_failure(seeded: Session) -> None:
    _add(seeded, 6)
    seeded.commit()

    stats = backfill_tier1(
        seeded, since=None, limit=None, sleep=0, dry_run=False, fetch=lambda u: ""
    )

    assert stats.fetch_failed == stats.scanned
    assert stats.fetched == 0


def test_since_and_limit(seeded: Session) -> None:
    old = _add(seeded, 7, datetime.date(2026, 1, 1))
    new1 = _add(seeded, 8, datetime.date(2026, 10, 1))
    new2 = _add(seeded, 9, datetime.date(2026, 10, 2))
    seeded.commit()
    since = datetime.date(2026, 10, 1)

    stats = backfill_tier1(seeded, since=since, limit=1, sleep=0, dry_run=False, fetch=_fetch)

    assert stats.scanned == 1
    assert _actors(seeded, old) == []
    assert _actors(seeded, new1) == ["Kimsuky"]  # id terkecil lebih dulu
    assert _actors(seeded, new2) == []
