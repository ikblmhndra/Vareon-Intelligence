"""Ambang `compute_health` (dead, degraded, zero_yield, ok, stale) dan aturan baru ROADMAP #24:
run yang selesai dengan item gagal (`items_failed > 0`) membuat scraper `degraded`, baris `running`
(sedang jalan atau yatim) bukan hasil, dan tiap status bermasalah punya alasan satu kalimat.

Sebelum ini ambang-ambang itu tidak punya test sama sekali (hanya cabang `disabled`)."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any

from cti_scraper.base import ScraperMeta
from cti_scraper.health import (
    compute_health,
    consecutive_failing,
    explain_health,
    summarize_fleet_health,
)
from cti_scraper.runner import final_status

UTC = datetime.UTC
NOW = datetime.datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def meta() -> ScraperMeta:
    return ScraperMeta(
        id="x",
        source="X",
        schedule="*/15 * * * *",
        legacy_label="X",
        legacy_script="x",
    )


def run(
    status: str,
    *,
    minutes_ago: int = 5,
    failed: int = 0,
    errors: list[dict[str, str]] | None = None,
) -> Any:
    return SimpleNamespace(
        status=status,
        started_at=NOW - datetime.timedelta(minutes=minutes_ago),
        items_failed=failed,
        errors=errors or [],
    )


def health(runs: list[Any]) -> str:
    return compute_health(meta(), None, runs, now=NOW)


# -- ambang yang sudah ada, kini terkunci ------------------------------------------------------


def test_a_clean_recent_run_is_ok() -> None:
    assert health([run("ok")]) == "ok"


def test_no_runs_at_all_is_stale() -> None:
    assert health([]) == "stale"


def test_a_run_older_than_three_intervals_is_dead() -> None:
    assert health([run("ok", minutes_ago=15 * 3 + 1)]) == "dead"
    assert health([run("ok", minutes_ago=15 * 3 - 1)]) == "ok"


def test_error_statuses_degrade_on_a_single_run() -> None:
    for status in ("fetch_error", "parse_error", "rate_limited", "timeout", "backpressure"):
        assert health([run(status)]) == "degraded"


def test_three_empty_runs_in_a_row_are_zero_yield() -> None:
    assert health([run("empty", minutes_ago=m) for m in (5, 20, 35)]) == "zero_yield"
    assert health([run("empty"), run("ok", minutes_ago=20), run("empty", minutes_ago=35)]) == "ok"


# -- aturan baru -------------------------------------------------------------------------------


def test_failed_items_degrade_a_run_that_would_otherwise_be_ok() -> None:
    assert health([run("ok", failed=4)]) == "degraded"
    assert health([run("partial", failed=4)]) == "degraded"


def test_a_partial_run_without_failed_items_stays_ok() -> None:
    """`partial` karena terpotong `max_items` (new_cve) bukan kegagalan."""
    assert health([run("partial", failed=0)]) == "ok"


def test_running_rows_are_not_a_result() -> None:
    """Run yang sedang jalan (atau yatim) tidak boleh menutupi kegagalan sebelumnya."""
    assert health([run("running", minutes_ago=1), run("parse_error", minutes_ago=16)]) == "degraded"
    assert health([run("running", minutes_ago=1), run("ok", minutes_ago=16)]) == "ok"


def test_only_running_rows_fall_back_to_the_time_rule() -> None:
    assert health([run("running", minutes_ago=2)]) == "ok"


def test_final_status_turns_an_ok_run_with_failed_items_into_partial() -> None:
    assert final_status("ok", 4) == "partial"
    assert final_status("ok", 0) == "ok"
    for untouched in ("empty", "partial", "fetch_error", "parse_error", "backpressure"):
        assert final_status(untouched, 4) == untouched


# -- alasan dan ringkasan ----------------------------------------------------------------------


def test_the_reason_names_the_failure_without_a_traceback() -> None:
    errors = [
        {
            "stage": "sink",
            "type": "UnknownAlertTopic",
            "message": "topic alert 'github_poc'",
            "traceback": "Traceback (most recent call last): secret",
        }
    ]
    reason = explain_health("degraded", [run("partial", failed=4, errors=errors)])

    assert reason is not None
    assert "4 item(s) failed in the last run" in reason and "sink/UnknownAlertTopic" in reason
    assert "Traceback" not in reason


def test_reasons_for_the_other_problem_statuses() -> None:
    assert explain_health("degraded", [run("parse_error")]) == "last run parse_error"
    assert explain_health("stale", []) == "never ran"
    assert "3 empty runs" in (explain_health("zero_yield", [run("empty")]) or "")
    assert explain_health("ok", [run("ok")]) is None
    assert explain_health("disabled", []) is None


def test_consecutive_failing_counts_the_newest_failing_runs_only() -> None:
    runs = [run("partial", failed=1), run("fetch_error", minutes_ago=20), run("ok", minutes_ago=35)]
    assert consecutive_failing(runs) == 2
    assert consecutive_failing([run("ok"), run("fetch_error", minutes_ago=20)]) == 0


def test_the_fleet_summary_carries_reason_counts_and_last_success() -> None:
    cls = SimpleNamespace(meta=meta())
    ok_at = NOW - datetime.timedelta(hours=1)
    runs = {"x": [run("partial", failed=4), run("ok", minutes_ago=60)]}

    [entry] = summarize_fleet_health(
        {"x": cls},
        {},
        runs,
        now=NOW,
        last_success={"x": ok_at},  # type: ignore[dict-item]
    )

    assert entry.status == "degraded" and entry.items_failed_last == 4
    assert entry.consecutive_failing == 1 and entry.last_success_at == ok_at
    assert entry.reason and "4 item(s)" in entry.reason
