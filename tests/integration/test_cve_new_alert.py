"""Ringkasan Telegram CVE baru -- jalur DB-nya di Postgres beneran (`cti_scraper.cve_alert`).

Yang dikunci lewat `Runner` sungguhan (bukan memanggil fungsi langsung, supaya penempatan hook di
akhir run ikut teruji): hanya baris yang BARU DIBUAT yang diumumkan, satu pesan per client per run,
CVE lama / false positive / tanpa tanggal tidak diumumkan, dan kegagalan kirim tidak menggagalkan
ingest. Formatnya dites murni di `tests/unit/test_cve_alert.py`."""

from __future__ import annotations

import datetime
from collections.abc import Callable, Iterator

import pytest
from cti_core.db.models.auth import Client
from cti_core.db.models.cve import CveFalsePositive, CveTracker
from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.items import CveItem, Item
from cti_scraper.runner import Runner
from sqlalchemy import select
from sqlalchemy.orm import Session

SID = "test-new-cve"
TODAY = datetime.datetime.now(datetime.UTC).date()


@pytest.fixture
def session(_migrated_schema: None) -> Iterator[Session]:
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    for cid in ("acme", "globex"):
        s.add(Client(client_id=cid, name=cid.title()))
    s.flush()
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr("cti_alerts.telegram.send_alert", lambda t, m: messages.append((t, m)))
    return messages


def make_scraper(feed: Callable[[], list[Item]]) -> type[BaseScraper]:
    class _Scraper(BaseScraper):
        __abstract__ = True
        meta = ScraperMeta(id=SID, source="Test", schedule="0 * * * *", max_items=300)

        def dedup_key(self, item: Item) -> str | None:
            return None  # sama dengan `new_cve`: selalu upsert ulang

        def fetch(self, ctx: ScrapeContext) -> Iterator[Item]:
            yield from feed()

    return _Scraper


def item(cve_id: str, client: str = "acme", **kw: object) -> CveItem:
    base: dict[str, object] = {
        "cve_id": cve_id,
        "client_id": client,
        "tech": "nginx",
        "summary": f"ringkasan {cve_id}",
        "published": TODAY,
        "cve_severity": "HIGH",
        "cve_score": 7.5,
        "link": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
    }
    base.update(kw)
    return CveItem(**base)  # type: ignore[arg-type]


def run(session: Session, *items: CveItem) -> None:
    Runner(make_scraper(lambda: list(items)), session=session, cold_start_max_items=99).execute()


def test_new_cves_for_a_client_are_announced_in_one_message(
    session: Session, sent: list[tuple[str, str]]
) -> None:
    run(session, item("CVE-2026-7001"), item("CVE-2026-7002", cve_severity="CRITICAL"))

    assert len(sent) == 1
    topic, text = sent[0]
    assert topic == "cve_new"
    assert "Acme" in text and "CVE-2026-7001" in text and "CVE-2026-7002" in text
    assert text.index("CVE-2026-7002") < text.index("CVE-2026-7001")  # CRITICAL dulu


def test_each_client_gets_its_own_message(session: Session, sent: list[tuple[str, str]]) -> None:
    run(session, item("CVE-2026-7010", "acme"), item("CVE-2026-7010", "globex"))

    assert len(sent) == 2
    assert {("Acme" in t) for _, t in sent} == {True, False}
    assert {("Globex" in t) for _, t in sent} == {True, False}


def test_an_update_of_an_existing_row_is_not_announced_again(
    session: Session, sent: list[tuple[str, str]]
) -> None:
    run(session, item("CVE-2026-7020"))
    assert len(sent) == 1

    run(session, item("CVE-2026-7020", summary="skor diperbarui MITRE", cve_score=9.8))

    assert len(sent) == 1  # run kedua = UPDATE (scraper selalu upsert ulang), bukan CVE baru


def test_only_the_new_ones_are_announced_when_a_run_mixes_new_and_known(
    session: Session, sent: list[tuple[str, str]]
) -> None:
    run(session, item("CVE-2026-7030"))
    sent.clear()

    run(session, item("CVE-2026-7030"), item("CVE-2026-7031"))

    assert len(sent) == 1
    assert "CVE-2026-7031" in sent[0][1] and "CVE-2026-7030" not in sent[0][1]


def test_old_cves_are_stored_but_not_announced(
    session: Session, sent: list[tuple[str, str]]
) -> None:
    """Tech baru / backfill / database baru: CVE lama masuk tracker, channel tidak dibanjiri."""
    old = TODAY - datetime.timedelta(days=30)
    run(session, item("CVE-2026-7040", published=old), item("CVE-2026-7041", published=None))

    assert sent == []
    stored = (
        session.execute(
            select(CveTracker.cve_id).where(
                CveTracker.cve_id.in_(["CVE-2026-7040", "CVE-2026-7041"])
            )
        )
        .scalars()
        .all()
    )
    assert sorted(stored) == ["CVE-2026-7040", "CVE-2026-7041"]


def test_a_false_positive_is_not_announced(session: Session, sent: list[tuple[str, str]]) -> None:
    session.add(CveFalsePositive(cve_id="CVE-2026-7050", client_id="acme"))
    session.flush()

    run(session, item("CVE-2026-7050"), item("CVE-2026-7051"))

    assert len(sent) == 1
    assert "CVE-2026-7051" in sent[0][1] and "CVE-2026-7050" not in sent[0][1]


def test_a_failing_send_does_not_fail_the_run_or_lose_the_cve(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(topic: str, msg: str) -> None:
        raise RuntimeError("telegram mati")

    monkeypatch.setattr("cti_alerts.telegram.send_alert", boom)

    result = Runner(
        make_scraper(lambda: [item("CVE-2026-7060")]), session=session, cold_start_max_items=99
    ).execute()

    assert result.status == "ok" and result.items_new == 1
    assert session.execute(
        select(CveTracker).where(CveTracker.cve_id == "CVE-2026-7060")
    ).scalar_one()


def test_an_unregistered_topic_is_swallowed(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prod yang `.env`-nya belum punya `cve_new` -> `UnknownAlertTopic`; ingest tetap jalan."""
    from cti_alerts.telegram import UnknownAlertTopic

    def unknown(topic: str, msg: str) -> None:
        raise UnknownAlertTopic(topic)

    monkeypatch.setattr("cti_alerts.telegram.send_alert", unknown)

    result = Runner(
        make_scraper(lambda: [item("CVE-2026-7070")]), session=session, cold_start_max_items=99
    ).execute()

    assert result.status == "ok" and result.items_new == 1


def test_the_collected_rows_do_not_leak_into_the_next_run(
    session: Session, sent: list[tuple[str, str]]
) -> None:
    run(session, item("CVE-2026-7080"))
    sent.clear()

    run(session)  # run kosong

    assert sent == []
    assert "cve_new_rows" not in session.info
