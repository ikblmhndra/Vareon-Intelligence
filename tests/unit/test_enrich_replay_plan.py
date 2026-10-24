"""`cti_core.enrich_replay` -- keputusan murni replay otomatis (spec 4.2): berapa artikel yang
boleh dikirim ulang sekarang, tergantung status LLM terakhir dan kedalaman antrian `enrich`."""

from __future__ import annotations

import datetime

import pytest
from cti_core.enrich_replay import BATCH, ReplayCandidate, is_fresh, plan_auto_replay

NOW = datetime.datetime(2026, 10, 24, 12, 0, tzinfo=datetime.UTC)
MAX_DEPTH = 2000


def make(n: int) -> list[ReplayCandidate]:
    return [
        ReplayCandidate(
            id=i,
            url=f"https://example.com/{i}",
            title=f"t{i}",
            source="s",
            scraper_id="x",
            posted_on=None,
            auto_replay_count=0,
            last_auto_replay_at=None,
        )
        for i in range(n)
    ]


def plan(cands, *, status="ok", depth: int | None = 0):
    return plan_auto_replay(
        cands, last_status=status, queue_depth=depth, max_depth=MAX_DEPTH, now=NOW
    )


def test_healthy_sends_a_full_batch_oldest_first() -> None:
    cands = make(25)
    out = plan(cands)
    assert len(out) == BATCH == 20
    assert [c.id for c in out] == list(range(20))


@pytest.mark.parametrize("status", ["error", "empty", None])
def test_unknown_model_sends_exactly_one_canary(status) -> None:
    assert [c.id for c in plan(make(25), status=status)] == [0]


def test_healthy_is_capped_by_free_queue_room() -> None:
    assert len(plan(make(25), depth=MAX_DEPTH - 5)) == 5


def test_healthy_with_full_queue_sends_nothing() -> None:
    assert plan(make(25), depth=MAX_DEPTH) == []
    assert plan(make(25), depth=MAX_DEPTH + 10) == []


def test_unknown_depth_sends_only_the_canary() -> None:
    assert len(plan(make(25), depth=None)) == 1


def test_no_candidates() -> None:
    assert plan([]) == []


def test_is_fresh_window() -> None:
    today = NOW.date()
    assert is_fresh(today, NOW)
    assert is_fresh(today - datetime.timedelta(days=1), NOW)
    assert not is_fresh(today - datetime.timedelta(days=2), NOW)
    assert not is_fresh(None, NOW)
