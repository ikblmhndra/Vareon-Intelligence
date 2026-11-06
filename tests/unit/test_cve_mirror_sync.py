"""Bagian murni ingest mirror CVE (`cti_core.cve_record`, `cti_core.cve_mirror_sync`): parser
record, format `delta.json`/`deltaLog.json` asli, aturan catch-up, state, dan validasi tautan.
Jalur DB (siklus `sync_once` penuh) ada di `tests/integration/test_cve_mirror_sync.py`."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import pytest
from cti_core.cve_mirror_sync import (
    FETCH_GAP,
    POLL_GAP,
    RECORD_URL_PREFIX,
    DeltaItem,
    FetchError,
    PendingItem,
    ReconcileState,
    SyncState,
    needs_catch_up,
    parse_delta_entry,
    parse_delta_log,
    reconcile_plan,
    valid_record_link,
)
from cti_core.cve_record import cna_summary, cve_state, parse_cve_record

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "spike_cve"
UTC = datetime.UTC
T0 = datetime.datetime(2026, 10, 7, 11, 0, tzinfo=UTC)
RAW = "https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/2026/42xxx/CVE-2026-42713.json"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


# ── parser record ─────────────────────────────────────────────────────────────────────────────


def test_parse_real_record_fields() -> None:
    data = load("CVE-2025-0282")
    d = parse_cve_record(data, cve_id="CVE-2025-0282", link="L", summary=cna_summary(data))
    f = d.fields
    assert f["cve_id"] == "CVE-2025-0282" and f["link"] == "L"
    assert f["published"] == datetime.date(2025, 1, 8)
    assert f["published_at"] == datetime.datetime(2025, 1, 8, 22, 15, 9, 386000, tzinfo=UTC)
    assert f["cve_modified_date"] == datetime.date(2026, 10, 1)
    assert f["cve_score"] == 9.0 and f["cve_severity"] == "CRITICAL"
    assert f["cvss_vector"].startswith("CVSS:3.1/")
    assert f["summary"].startswith("A stack-based buffer overflow")
    assert "Connect Secure: <= 22.7R2.4" in f["affected"]
    assert ("Ivanti", "Connect Secure") in {(e.vendor, e.product) for e in d.affected_entries}
    assert "Ivanti" in d.products


def test_cna_summary_and_state_tolerate_odd_shapes() -> None:
    assert cna_summary({}) == ""
    assert (
        cna_summary({"containers": {"cna": {"descriptions": [{"lang": "es", "value": "hola"}]}}})
        == ""
    )
    assert (
        cna_summary(
            {"containers": {"cna": {"descriptions": [{"lang": "en-US", "value": "hello"}]}}}
        )
        == "hello"
    )
    assert cve_state({}) == "" and cve_state({"cveMetadata": {"state": "REJECTED"}}) == "REJECTED"


def test_record_without_metrics_keeps_legacy_defaults() -> None:
    d = parse_cve_record({"containers": {"cna": {}}}, cve_id="CVE-2026-1", link="L", summary="s")
    # perilaku lama `new_cve` (ditulis ke cve_tracker): skor 0.0 dan "No solution yet"
    assert d.fields["cve_score"] == 0.0 and d.fields["cve_severity"] is None
    assert d.fields["solutions"] == "No solution yet" and d.fields["published"] is None


# ── delta ─────────────────────────────────────────────────────────────────────────────────────


def entry(fetch_time: str, new: list[str], updated: list[str] | None = None) -> dict[str, Any]:
    def row(cve: str, when: str) -> dict[str, str]:
        return {"cveId": cve, "githubLink": RAW, "dateUpdated": when}

    return {
        "fetchTime": fetch_time,
        "numberOfChanges": len(new) + len(updated or []),
        "new": [row(c, "2026-10-07T10:57:48.445Z") for c in new],
        "updated": [row(c, "2026-10-07T10:59:00.000Z") for c in updated or []],
        "error": [],
    }


def test_parse_delta_entry_dedupes_keeping_the_latest_update() -> None:
    e = parse_delta_entry(
        entry("2026-10-07T11:03:20.439Z", ["CVE-2026-1", "CVE-2026-2"], ["CVE-2026-1"])
    )
    assert e.fetch_time == datetime.datetime(2026, 10, 7, 11, 3, 20, 439000, tzinfo=UTC)
    by_id = {i.cve_id: i for i in e.items}
    assert set(by_id) == {"CVE-2026-1", "CVE-2026-2"}
    assert by_id["CVE-2026-1"].date_updated == datetime.datetime(2026, 10, 7, 10, 59, tzinfo=UTC)


@pytest.mark.parametrize("raw", [[], "x", {}, {"fetchTime": 5}, {"fetchTime": "kemarin"}])
def test_parse_delta_entry_rejects_unusable_input(raw: Any) -> None:
    with pytest.raises(FetchError):
        parse_delta_entry(raw)


def test_parse_delta_entry_skips_malformed_items() -> None:
    raw = entry("2026-10-07T11:03:20.439Z", ["CVE-2026-1"])
    raw["new"] += [None, {"cveId": "CVE-2026-9"}, {"githubLink": RAW}, "x"]
    assert [i.cve_id for i in parse_delta_entry(raw).items] == ["CVE-2026-1"]


def test_parse_delta_log_sorts_oldest_first_and_skips_broken_elements() -> None:
    log = [
        entry("2026-10-07T11:03:20.000Z", ["CVE-2026-3"]),
        {"broken": True},
        entry("2026-10-07T10:03:20.000Z", ["CVE-2026-1"]),
    ]
    assert [e.items[0].cve_id for e in parse_delta_log(log)] == ["CVE-2026-1", "CVE-2026-3"]
    with pytest.raises(FetchError):
        parse_delta_log({"fetchTime": "x"})


# ── catch-up ──────────────────────────────────────────────────────────────────────────────────


def test_no_catch_up_on_first_run_or_old_fetch_time() -> None:
    assert not needs_catch_up(SyncState(), T0, T0)  # riwayat = urusan backfill
    s = SyncState(fetch_time=T0, polled_at=T0)
    assert not needs_catch_up(s, T0, T0)
    assert not needs_catch_up(s, T0 - FETCH_GAP * 2, T0)


def test_catch_up_when_we_polled_late() -> None:
    s = SyncState(fetch_time=T0, polled_at=T0)
    soon = T0 + datetime.timedelta(minutes=5)
    assert not needs_catch_up(s, soon, soon)
    late = T0 + POLL_GAP + datetime.timedelta(minutes=1)
    assert needs_catch_up(s, late, late)


def test_catch_up_when_fetch_time_jumps_even_if_we_polled_on_time() -> None:
    s = SyncState(fetch_time=T0, polled_at=T0)
    jump = T0 + FETCH_GAP + datetime.timedelta(minutes=1)
    assert needs_catch_up(s, jump, T0 + datetime.timedelta(minutes=5))
    assert not needs_catch_up(s, T0 + FETCH_GAP, T0 + datetime.timedelta(minutes=5))


# ── state dan tautan ──────────────────────────────────────────────────────────────────────────


def test_state_roundtrip_and_garbage_tolerance() -> None:
    s = SyncState(fetch_time=T0, polled_at=T0, pending=[PendingItem("CVE-2026-1", RAW, 2)])
    again = SyncState.load(json.loads(json.dumps(s.dump())))
    assert again == s
    for junk in (None, "x", [], {"fetch_time": "bukan tanggal", "pending": [1, {"cve_id": "x"}]}):
        loaded = SyncState.load(junk)
        assert loaded.fetch_time is None and loaded.pending == []
    naive = SyncState.load({"fetch_time": "2026-10-07T11:00:00"})
    assert naive.fetch_time == T0


@pytest.mark.parametrize(
    ("link", "ok"),
    [
        (RAW, True),
        ("https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/../x.json", False),
        ("https://raw.githubusercontent.com/evil/repo/main/CVE-1.json", False),
        ("http://raw.githubusercontent.com/CVEProject/cvelistV5/main/a.json", False),
        ("https://169.254.169.254/CVEProject/cvelistV5/a.json", False),
        ("https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/a.txt", False),
    ],
)
def test_only_cvelist_record_links_are_fetched(link: str, ok: bool) -> None:
    assert valid_record_link(link) is ok


# ── reconcile_plan ────────────────────────────────────────────────────────────────────────────

R0 = datetime.datetime(2026, 11, 3, 19, 50, tzinfo=UTC)
R1 = R0 + datetime.timedelta(minutes=5)


def item(cve: str, at: datetime.datetime | None) -> DeltaItem:
    return DeltaItem(
        cve_id=cve, link=f"{RECORD_URL_PREFIX}main/cves/2026/95xxx/{cve}.json", date_updated=at
    )


def test_plan_includes_missing_records() -> None:
    plan = reconcile_plan([item("CVE-2026-95731", R0)], {}, {})
    assert [i.cve_id for i in plan] == ["CVE-2026-95731"]


def test_plan_includes_outdated_records() -> None:
    assert reconcile_plan([item("CVE-2026-1", R1)], {"CVE-2026-1": R0}, {})[0].date_updated == R1


def test_plan_skips_current_and_newer_mirror_versions() -> None:
    assert reconcile_plan([item("CVE-2026-1", R0)], {"CVE-2026-1": R0}, {}) == []
    assert reconcile_plan([item("CVE-2026-1", R0)], {"CVE-2026-1": R1}, {}) == []


def test_plan_respects_skip_with_same_version() -> None:
    assert reconcile_plan([item("CVE-2026-1", R0)], {}, {"CVE-2026-1": R0}) == []
    assert len(reconcile_plan([item("CVE-2026-1", R1)], {}, {"CVE-2026-1": R0})) == 1


def test_plan_dedupes_to_latest_version_across_windows() -> None:
    plan = reconcile_plan([item("CVE-2026-1", R0), item("CVE-2026-1", R1)], {}, {})
    assert [(i.cve_id, i.date_updated) for i in plan] == [("CVE-2026-1", R1)]


def test_plan_mirror_without_version_counts_as_outdated() -> None:
    assert len(reconcile_plan([item("CVE-2026-1", R0)], {"CVE-2026-1": None}, {})) == 1


def test_plan_unversioned_log_item_only_when_missing_and_sorted() -> None:
    plan = reconcile_plan(
        [item("CVE-2026-2", None), item("CVE-2026-1", None), item("CVE-2026-3", None)],
        {"CVE-2026-3": R0},
        {},
    )
    assert [i.cve_id for i in plan] == ["CVE-2026-1", "CVE-2026-2"]


def test_reconcile_state_roundtrip() -> None:
    s = ReconcileState(
        skips={"CVE-2026-1": R0, "CVE-2026-2": None}, last_report={"fixed": 2}, ran_at=R1
    )
    assert ReconcileState.load(s.dump()) == s
    assert ReconcileState.load(None) == ReconcileState(skips={}, last_report=None, ran_at=None)
