"""Siklus ingest mirror CVE (`cti_core.cve_mirror_sync.sync_once`) di Postgres beneran, dengan
fetcher palsu yang menyajikan `delta.json`/`deltaLog.json`/record: kursor dan state, catch-up,
retry/pending, kegagalan satu berkas, record REJECTED/di luar retensi, dan batas berkas per run.
Parser dan format delta dites murni di `tests/unit/test_cve_mirror_sync.py`."""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cti_core.cve_mirror_sync import (
    DELTA_LOG_URL,
    DELTA_URL,
    MAX_ATTEMPTS,
    STATE_KEY,
    FetchError,
    SyncState,
    purge_expired,
    sync_once,
)
from cti_core.db.models.catalog import CatalogFamily, CatalogVendor
from cti_core.db.models.cve_mirror import CveRecord
from cti_core.db.repositories.catalog import CveMirrorRepo
from cti_core.db.repositories.report_state import JobStateRepo
from sqlalchemy import func, select
from sqlalchemy.orm import Session

UTC = datetime.UTC
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "spike_cve"
BASE = "https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/2025/"
NOW = datetime.datetime(2026, 10, 7, 11, 5, tzinfo=UTC)


def link(cve: str) -> str:
    return f"{BASE}{cve}.json"


def record(cve: str, *, vendor: str = "Fortinet", product: str = "FortiOS", **meta: Any) -> dict:
    return {
        "cveMetadata": {
            "cveId": cve,
            "state": "PUBLISHED",
            "datePublished": "2026-03-01T10:00:00.000Z",
            "dateUpdated": "2026-03-02T10:00:00.000Z",
            **meta,
        },
        "containers": {
            "cna": {
                "descriptions": [{"lang": "en", "value": f"{cve} bug"}],
                "affected": [{"vendor": vendor, "product": product}],
            }
        },
    }


def delta(fetch_time: str, new: list[str] = (), updated: list[str] = ()) -> dict:
    def row(c: str) -> dict:
        return {"cveId": c, "githubLink": link(c), "dateUpdated": "2026-10-07T10:57:00.000Z"}

    return {
        "fetchTime": fetch_time,
        "numberOfChanges": len(new) + len(updated),
        "new": [row(c) for c in new],
        "updated": [row(c) for c in updated],
        "error": [],
    }


class FakeNet:
    def __init__(self) -> None:
        self.files: dict[str, Any] = {}
        self.fail: set[str] = set()
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        if url in self.fail or url not in self.files:
            raise FetchError(f"gagal {url}")
        value = self.files[url]
        return value if isinstance(value, bytes) else json.dumps(value).encode()

    def serve(self, d: dict, *recs: dict) -> None:
        self.files[DELTA_URL] = d
        for r in recs:
            self.files[link(r["cveMetadata"]["cveId"])] = r


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


def state(s: Session) -> SyncState:
    return SyncState.load(JobStateRepo(s).get(STATE_KEY))


def count(s: Session) -> int:
    return s.scalar(select(func.count()).select_from(CveRecord)) or 0


def at(minutes: int) -> datetime.datetime:
    return NOW + datetime.timedelta(minutes=minutes)


def test_first_run_stores_records_and_sets_cursor(session: Session) -> None:
    net = FakeNet()
    net.serve(delta("2026-10-07T11:03:20.439Z", ["CVE-2025-0001"]), record("CVE-2025-0001"))
    r = sync_once(session, net, NOW)
    assert (r.status, r.created, r.caught_up) == ("ok", 1, False)
    row = session.get(CveRecord, "CVE-2025-0001")
    assert row is not None and row.summary == "CVE-2025-0001 bug"
    assert row.link == "https://nvd.nist.gov/vuln/detail/CVE-2025-0001" and row.has_identity
    assert DELTA_LOG_URL not in net.calls  # run pertama tidak membaca log (riwayat = backfill)
    s = state(session)
    assert s.fetch_time == datetime.datetime(2026, 10, 7, 11, 3, 20, 439000, tzinfo=UTC)
    assert s.polled_at == NOW and s.pending == []


def test_same_fetch_time_is_a_noop_but_refreshes_polled_at(session: Session) -> None:
    net = FakeNet()
    net.serve(delta("2026-10-07T11:03:20.439Z", ["CVE-2025-0001"]), record("CVE-2025-0001"))
    sync_once(session, net, NOW)
    net.calls.clear()
    r = sync_once(session, net, at(5))
    assert r.status == "noop" and r.created == 0
    assert net.calls == [DELTA_URL]  # tidak mengunduh ulang record
    assert state(session).polled_at == at(5)


def test_updated_record_is_updated_and_older_one_is_stale(session: Session) -> None:
    net = FakeNet()
    net.serve(delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001"]), record("CVE-2025-0001"))
    sync_once(session, net, NOW)
    newer = record("CVE-2025-0001", dateUpdated="2026-03-05T10:00:00.000Z")
    newer["containers"]["cna"]["descriptions"][0]["value"] = "diperbarui"
    net.serve(delta("2026-10-07T11:08:20.000Z", updated=["CVE-2025-0001"]), newer)
    assert sync_once(session, net, at(5)).updated == 1
    cve = session.get(CveRecord, "CVE-2025-0001")
    assert cve is not None and cve.summary == "diperbarui"
    older = record("CVE-2025-0001", dateUpdated="2026-03-03T10:00:00.000Z")
    net.serve(delta("2026-10-07T11:13:20.000Z", updated=["CVE-2025-0001"]), older)
    assert sync_once(session, net, at(10)).stale == 1
    session.refresh(cve)
    assert cve.summary == "diperbarui"


def test_failed_file_is_retried_next_cycle_without_blocking_others(session: Session) -> None:
    net = FakeNet()
    net.serve(
        delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001", "CVE-2025-0002"]),
        record("CVE-2025-0001"),
        record("CVE-2025-0002"),
    )
    net.fail.add(link("CVE-2025-0001"))
    r = sync_once(session, net, NOW)
    assert (r.created, r.failed, r.pending) == (1, 1, 1)
    assert [(p.cve_id, p.attempts) for p in state(session).pending] == [("CVE-2025-0001", 1)]
    assert session.get(CveRecord, "CVE-2025-0002") is not None

    net.fail.clear()  # siklus berikut: fetchTime sama, tapi pending tetap dicoba
    r = sync_once(session, net, at(5))
    assert (r.status, r.created, r.pending) == ("noop", 1, 0)
    assert state(session).pending == []


def test_item_is_dropped_after_max_attempts(session: Session) -> None:
    net = FakeNet()
    net.serve(delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001"]), record("CVE-2025-0001"))
    net.fail.add(link("CVE-2025-0001"))
    reports = [sync_once(session, net, at(5 * i)) for i in range(MAX_ATTEMPTS)]
    assert [r.failed for r in reports] == [1] * (MAX_ATTEMPTS - 1) + [0]
    assert reports[-1].dropped == 1 and state(session).pending == []


def test_delta_failure_is_reported_and_leaves_state_untouched(session: Session) -> None:
    net = FakeNet()
    net.serve(delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001"]), record("CVE-2025-0001"))
    sync_once(session, net, NOW)
    before = JobStateRepo(session).get(STATE_KEY)
    net.files[DELTA_URL] = b"<html>502</html>"
    r = sync_once(session, net, at(5))
    assert r.status == "error" and "JSON" in r.error
    assert JobStateRepo(session).get(STATE_KEY) == before


def test_catch_up_after_outage_replays_missed_windows_from_the_log(session: Session) -> None:
    net = FakeNet()
    net.serve(delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001"]), record("CVE-2025-0001"))
    sync_once(session, net, NOW)

    # worker mati 30 menit: dua jendela terlewat; delta.json hanya memuat yang terbaru
    missed = [
        delta("2026-10-07T11:20:00.000Z", ["CVE-2025-0002"]),
        delta("2026-10-07T11:35:00.000Z", ["CVE-2025-0003"]),
    ]
    latest = delta("2026-10-07T11:40:00.000Z", ["CVE-2025-0004"])
    net.serve(latest, record("CVE-2025-0002"), record("CVE-2025-0003"), record("CVE-2025-0004"))
    net.files[DELTA_LOG_URL] = [
        latest,
        *reversed(missed),
        delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001"]),
        delta("2026-10-07T10:00:00.000Z", ["CVE-2025-0000"]),  # lebih lama dari kursor
    ]
    r = sync_once(session, net, at(35))
    assert r.caught_up and not r.gap_unrecoverable
    assert r.created == 3
    assert {c for (c,) in session.execute(select(CveRecord.cve_id))} == {
        "CVE-2025-0001",
        "CVE-2025-0002",
        "CVE-2025-0003",
        "CVE-2025-0004",
    }
    assert state(session).fetch_time == datetime.datetime(2026, 10, 7, 11, 40, tzinfo=UTC)


def test_catch_up_flags_a_gap_older_than_the_log(session: Session) -> None:
    net = FakeNet()
    net.serve(delta("2026-09-01T00:00:00.000Z", ["CVE-2025-0001"]), record("CVE-2025-0001"))
    sync_once(session, net, datetime.datetime(2026, 9, 1, 0, 5, tzinfo=UTC))
    latest = delta("2026-10-07T11:40:00.000Z", ["CVE-2025-0002"])
    net.serve(latest, record("CVE-2025-0002"))
    net.files[DELTA_LOG_URL] = [latest, delta("2026-09-20T00:00:00.000Z")]
    r = sync_once(session, net, at(35))
    assert r.caught_up and r.gap_unrecoverable and r.created == 1


def test_catch_up_fetch_failure_keeps_the_cursor_so_the_next_tick_retries(session: Session) -> None:
    net = FakeNet()
    net.serve(delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001"]), record("CVE-2025-0001"))
    sync_once(session, net, NOW)
    net.serve(delta("2026-10-07T11:40:00.000Z", ["CVE-2025-0002"]), record("CVE-2025-0002"))
    r = sync_once(session, net, at(35))  # DELTA_LOG_URL tidak ada -> FetchError
    assert r.status == "error"
    assert state(session).fetch_time == datetime.datetime(2026, 10, 7, 11, 3, 20, tzinfo=UTC)


def test_rejected_record_is_removed_and_unknown_rejected_is_skipped(session: Session) -> None:
    net = FakeNet()
    net.serve(delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001"]), record("CVE-2025-0001"))
    sync_once(session, net, NOW)
    rejected = {"cveMetadata": {"cveId": "CVE-2025-0001", "state": "REJECTED"}, "containers": {}}
    other = {"cveMetadata": {"cveId": "CVE-2025-0009", "state": "REJECTED"}, "containers": {}}
    net.serve(
        delta("2026-10-07T11:08:20.000Z", updated=["CVE-2025-0001"], new=["CVE-2025-0009"]),
        rejected,
        other,
    )
    r = sync_once(session, net, at(5))
    assert (r.removed, r.skipped) == (1, 1) and count(session) == 0


def test_records_without_date_or_outside_retention_are_not_stored(session: Session) -> None:
    net = FakeNet()
    undated = record("CVE-2025-0001")
    del undated["cveMetadata"]["datePublished"]
    old = record("CVE-2025-0002", datePublished="2024-12-31T23:59:00.000Z")
    ok = record("CVE-2025-0003", datePublished="2025-01-01T00:00:00.000Z")
    net.serve(
        delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001", "CVE-2025-0002", "CVE-2025-0003"]),
        undated,
        old,
        ok,
    )
    r = sync_once(session, net, NOW)
    assert (r.created, r.skipped) == (1, 2)
    assert session.get(CveRecord, "CVE-2025-0003") is not None


def test_untrusted_links_are_never_fetched(session: Session) -> None:
    net = FakeNet()
    d = delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001"])
    d["new"][0]["githubLink"] = "http://169.254.169.254/latest/meta-data/x.json"
    d["new"].append({"cveId": "bukan-cve", "githubLink": link("CVE-2025-0002")})
    net.serve(d)
    r = sync_once(session, net, NOW)
    assert r.skipped == 2 and r.created == 0
    assert net.calls == [DELTA_URL]


def test_files_over_the_cap_carry_over_to_the_next_cycle(session: Session) -> None:
    net = FakeNet()
    ids = [f"CVE-2025-{i:04d}" for i in range(1, 6)]
    net.serve(delta("2026-10-07T11:03:20.000Z", ids), *(record(i) for i in ids))
    r = sync_once(session, net, NOW, max_files=2)
    assert (r.created, r.pending) == (2, 3)
    assert state(session).fetch_time is not None  # kursor maju; sisanya aman di pending
    assert sync_once(session, net, at(5), max_files=2).pending == 1
    assert sync_once(session, net, at(10), max_files=2).pending == 0
    assert count(session) == 5


def test_one_failing_record_does_not_abort_the_batch(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    net = FakeNet()
    net.serve(
        delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001", "CVE-2025-0002"]),
        record("CVE-2025-0001", vendor="Boom", product="Boom"),
        record("CVE-2025-0002"),
    )
    real = CveMirrorRepo.upsert

    def flaky(self: CveMirrorRepo, rec: Any, resolved: Any) -> Any:
        if rec.cve_id == "CVE-2025-0001":
            raise RuntimeError("boom")
        return real(self, rec, resolved)

    monkeypatch.setattr(CveMirrorRepo, "upsert", flaky)
    r = sync_once(session, net, NOW)
    assert (r.created, r.failed) == (1, 1)
    assert [p.cve_id for p in state(session).pending] == ["CVE-2025-0001"]


def test_real_records_flow_into_catalog_with_cvss(session: Session) -> None:
    net = FakeNet()
    recs = [
        json.loads((FIXTURES / f"{n}.json").read_text()) for n in ("CVE-2025-0282", "CVE-2025-1974")
    ]
    net.serve(delta("2026-10-07T11:03:20.000Z", [r["cveMetadata"]["cveId"] for r in recs]), *recs)
    assert sync_once(session, net, NOW).created == 2
    ivanti = session.get(CveRecord, "CVE-2025-0282")
    assert ivanti is not None and ivanti.cvss_severity == "CRITICAL" and ivanti.cvss_score == 9.0
    assert ivanti.solutions
    vendors = {v for (v,) in session.execute(select(CatalogVendor.key))}
    assert {"ivanti", "kubernetes"} <= vendors
    fams = {f for (f,) in session.execute(select(CatalogFamily.key))}
    assert {"connect secure", "ingress nginx"} <= fams


def test_record_without_metrics_stores_null_score_not_zero(session: Session) -> None:
    net = FakeNet()
    net.serve(delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001"]), record("CVE-2025-0001"))
    sync_once(session, net, NOW)
    row = session.get(CveRecord, "CVE-2025-0001")
    assert row is not None and row.cvss_score is None and row.cvss_vector is None


def test_purge_expired_follows_the_calendar_year_rule(session: Session) -> None:
    net = FakeNet()
    net.serve(
        delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001", "CVE-2025-0002"]),
        record("CVE-2025-0001", datePublished="2025-06-01T00:00:00.000Z"),
        record("CVE-2025-0002", datePublished="2026-06-01T00:00:00.000Z"),
    )
    sync_once(session, net, NOW)
    assert purge_expired(session, datetime.date(2026, 12, 31)) == 0
    assert purge_expired(session, datetime.date(2027, 1, 1)) == 1
    assert count(session) == 1


def test_a_concurrent_sync_is_refused_while_the_lock_is_held(session: Session) -> None:
    from cti_core.db.engine import get_sync_engine
    from sqlalchemy import text

    net = FakeNet()
    net.serve(delta("2026-10-07T11:03:20.000Z", ["CVE-2025-0001"]), record("CVE-2025-0001"))
    from cti_core.cve_mirror_sync import LOCK_KEY

    with get_sync_engine().connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
        try:
            r = sync_once(session, net, NOW)
        finally:
            other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
    assert r.status == "locked" and net.calls == [] and count(session) == 0
    assert sync_once(session, net, NOW).created == 1  # kunci sudah lepas
