"""Pemeliharaan `scraper_runs` (ROADMAP #24): reaper untuk run yatim, purge riwayat lama, dan kolom
asal run (`celery_task_id`/`worker`/`attempt`) yang dulu tidak pernah terisi.

Dev 2026-10-17: 8 run `running` tertua 3 minggu (worker mati / redeploy), 25.864 baris tanpa purge,
dan ketiga kolom asal 0 dari 25.864."""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import pytest
from cti_core.db.models.scraper import ScraperRun
from cti_core.db.repositories.scraper import ScraperRunRepo
from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.items import Item
from cti_scraper.runner import Runner
from sqlalchemy import select
from sqlalchemy.orm import Session

NOW = datetime.datetime.now(datetime.UTC)


@pytest.fixture
def session(_migrated_schema: None) -> Iterator[Session]:
    """Sesi per-test yang boleh commit (repo-nya commit sendiri) tanpa bocor ke test lain."""
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


def add_run(session: Session, run_id: str, status: str, *, age: datetime.timedelta) -> None:
    session.add(
        ScraperRun(run_id=run_id, scraper_id="maint-test", status=status, started_at=NOW - age)
    )
    session.flush()


def status_of(session: Session, run_id: str) -> ScraperRun | None:
    return session.scalar(select(ScraperRun).where(ScraperRun.run_id == run_id))


def test_reaper_closes_only_stale_running_rows(session: Session) -> None:
    add_run(session, "stale", "running", age=datetime.timedelta(hours=5))
    add_run(session, "fresh", "running", age=datetime.timedelta(minutes=10))
    add_run(session, "old-ok", "ok", age=datetime.timedelta(hours=5))

    reaped = ScraperRunRepo(session).reap_stale_running(datetime.timedelta(hours=2))

    assert reaped == 1
    stale = status_of(session, "stale")
    assert stale is not None and stale.status == "timeout"
    assert stale.errors[0]["stage"] == "reaper" and stale.errors[0]["type"] == "StaleRun"
    assert stale.finished_at is None  # sengaja: bukan "hasil terbaru" di `latest_finished`
    assert status_of(session, "fresh").status == "running"  # type: ignore[union-attr]
    assert status_of(session, "old-ok").status == "ok"  # type: ignore[union-attr]


def test_purge_removes_old_history_but_never_a_running_row(session: Session) -> None:
    add_run(session, "ancient-ok", "ok", age=datetime.timedelta(days=100))
    add_run(session, "ancient-partial", "partial", age=datetime.timedelta(days=100))
    add_run(session, "ancient-running", "running", age=datetime.timedelta(days=100))
    add_run(session, "recent-ok", "ok", age=datetime.timedelta(days=10))

    deleted = ScraperRunRepo(session).purge_older_than(datetime.timedelta(days=90))

    assert deleted == 2
    assert (
        status_of(session, "ancient-ok") is None and status_of(session, "ancient-partial") is None
    )
    assert status_of(session, "ancient-running") is not None  # reaper yang menutupnya dulu
    assert status_of(session, "recent-ok") is not None


def test_last_success_ignores_runs_with_failed_items(session: Session) -> None:
    add_run(session, "clean", "ok", age=datetime.timedelta(hours=3))
    add_run(session, "failing", "partial", age=datetime.timedelta(hours=1))
    failing = status_of(session, "failing")
    assert failing is not None
    failing.items_failed = 4
    session.flush()

    last = ScraperRunRepo(session).last_success_by_scraper()

    assert abs((last["maint-test"] - (NOW - datetime.timedelta(hours=3))).total_seconds()) < 1


class _Quiet(BaseScraper):
    __abstract__ = True
    meta = ScraperMeta(id="maint-origin", source="Test", schedule="0 * * * *")

    def fetch(self, ctx: ScrapeContext) -> Iterator[Item]:
        return iter(())


def test_runner_records_where_the_run_came_from(session: Session) -> None:
    result = Runner(
        _Quiet,
        session=session,
        cold_start_max_items=0,
        celery_task_id="3f2a9c1e-aaaa-bbbb-cccc-1234567890ab",
        worker="worker@host1",
        attempt=3,
    ).execute()

    run = status_of(session, result.run_id)
    assert run is not None
    assert (run.celery_task_id, run.worker, run.attempt) == (
        "3f2a9c1e-aaaa-bbbb-cccc-1234567890ab",
        "worker@host1",
        3,
    )
