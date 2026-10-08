"""`Runner` menolak menjalankan scraper yang digantikan mirror CVE (cutover, ROADMAP #19 irisan 7):
status `disabled` tercatat, `fetch()` tidak dipanggil, dan flag cadangan / rollback
mengembalikannya."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from cti_core.config import CveMirrorSettings
from cti_core.db.models.scraper import ScraperRun
from cti_scraper import supersede
from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.items import CveItem, Item
from cti_scraper.runner import Runner
from sqlalchemy import select
from sqlalchemy.orm import Session

CALLS: list[int] = []


class _NewCve(BaseScraper):
    __abstract__ = True
    meta = ScraperMeta(id="new_cve", source="Test NVD", schedule="0 * * * *", max_items=10)

    def dedup_key(self, item: Item) -> str | None:
        return None

    def fetch(self, ctx: ScrapeContext) -> Iterator[Item]:
        CALLS.append(1)
        return iter(())


def use(monkeypatch: pytest.MonkeyPatch, **cfg: object) -> None:
    settings = SimpleNamespace(cve_mirror=CveMirrorSettings(**cfg))  # type: ignore[arg-type]
    monkeypatch.setattr(supersede, "get_settings", lambda: settings)


@pytest.fixture
def session(_migrated_schema: None) -> Iterator[Session]:
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    CALLS.clear()
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


def statuses(session: Session) -> list[str]:
    return [
        r for (r,) in session.execute(select(ScraperRun.status).order_by(ScraperRun.started_at))
    ]


def test_runner_refuses_new_cve_once_the_mirror_is_live(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, enabled=True, promote="live")
    result = Runner(_NewCve, session=session).execute()
    assert result.status == "disabled" and CALLS == []
    assert statuses(session) == ["disabled"]


def test_runner_still_runs_it_by_default_with_the_backup_flag_and_after_rollback(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    for cfg in (
        {},  # default: tidak ada yang berubah
        {"enabled": True, "promote": "live", "keep_legacy_new_cve": True},  # cadangan
        {"enabled": True, "promote": "shadow"},  # rollback
    ):
        CALLS.clear()
        use(monkeypatch, **cfg)
        result = Runner(_NewCve, session=session, cold_start_max_items=99).execute()
        assert result.status != "disabled" and CALLS == [1], cfg


def test_other_scrapers_are_unaffected_by_the_cutover(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Other(_NewCve):
        __abstract__ = True
        meta = ScraperMeta(id="other-feed", source="Other", schedule="0 * * * *", max_items=10)

    use(monkeypatch, enabled=True, promote="live")
    assert Runner(Other, session=session, cold_start_max_items=99).execute().status != "disabled"
    assert CALLS == [1]
    assert CveItem  # impor dipakai agar tipe item tetap terdaftar di registry sink
