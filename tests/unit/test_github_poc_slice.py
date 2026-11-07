"""`poc_slice`: irisan berputar per jam, pencarian GitHub per run dibatasi `POC_SEARCH_CAP`."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from cti_scrapers.feeds.github_poc_monitor import POC_SEARCH_CAP, poc_slice


def _entries(n: int) -> list[dict[str, object]]:
    return [{"cve_id": f"CVE-2026-{i:05d}", "poc_urls": set()} for i in range(n)]


def _at(hour: int) -> datetime:
    return datetime(2026, 11, 6) + timedelta(hours=hour)


def test_slice_returns_everything_under_cap() -> None:
    entries = _entries(POC_SEARCH_CAP)
    for hour in range(24):
        assert poc_slice(entries, _at(hour)) == entries


def test_slice_covers_every_cve_within_k_hours() -> None:
    entries = _entries(1425)
    k = math.ceil(len(entries) / POC_SEARCH_CAP)
    assert k == 6  # 1.425 kandidat (prod 2026-11-06) / 250
    slices = [{e["cve_id"] for e in poc_slice(entries, _at(h))} for h in range(k)]
    assert set().union(*slices) == {e["cve_id"] for e in entries}
    assert sum(len(s) for s in slices) == len(entries)  # saling lepas
    assert all(len(s) <= 2 * POC_SEARCH_CAP for s in slices)
    assert sum(len(s) for s in slices) / k <= POC_SEARCH_CAP


def test_slice_covers_every_cve_across_midnight() -> None:
    entries = _entries(1425)
    k = math.ceil(len(entries) / POC_SEARCH_CAP)
    slices = [{e["cve_id"] for e in poc_slice(entries, _at(h))} for h in range(22, 22 + k)]
    assert set().union(*slices) == {e["cve_id"] for e in entries}


def test_slice_covers_every_cve_when_k_exceeds_24() -> None:
    entries = _entries(25 * POC_SEARCH_CAP + 1)
    k = math.ceil(len(entries) / POC_SEARCH_CAP)
    assert k == 26
    slices = [{e["cve_id"] for e in poc_slice(entries, _at(h))} for h in range(7, 7 + k)]
    assert set().union(*slices) == {e["cve_id"] for e in entries}


def test_slice_is_stable_across_calls() -> None:
    entries = _entries(1425)
    assert poc_slice(entries, _at(3)) == poc_slice(entries, _at(3))
