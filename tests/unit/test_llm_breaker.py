"""`cti_core.llm.breaker` -- circuit breaker stateless dan batas dispatch (spec 4.4 / 4.5)."""

from __future__ import annotations

import datetime

import pytest
from cti_core.llm.breaker import (
    BATCH,
    Breaker,
    CallOutcome,
    breaker_state,
    dispatch_limit,
    is_fresh,
)

NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=datetime.UTC)
MIN = datetime.timedelta(minutes=1)


def fails(n: int, last_ago: datetime.timedelta, status: str = "error") -> list[CallOutcome]:
    """`n` kegagalan beruntun, terbaru dulu, yang terbaru `last_ago` lalu."""
    return [CallOutcome(status, NOW - last_ago - i * MIN) for i in range(n)]


def test_no_calls_closed() -> None:
    assert breaker_state([], NOW) == Breaker("closed", 0, None)


def test_ok_closed() -> None:
    assert breaker_state([CallOutcome("ok", NOW)], NOW).state == "closed"


def test_two_failures_closed() -> None:
    b = breaker_state(fails(2, MIN), NOW)
    assert b.state == "closed" and b.failures == 2 and b.retry_at is None


def test_ok_newest_stops_the_streak() -> None:
    recent = [CallOutcome("ok", NOW), *fails(5, MIN)]
    assert breaker_state(recent, NOW).state == "closed"


def test_three_failures_open() -> None:
    b = breaker_state(fails(3, MIN), NOW)
    assert b.state == "open" and b.failures == 3
    assert b.retry_at == NOW - MIN + 2 * MIN


def test_five_failures_cooldown_8_min() -> None:
    b = breaker_state(fails(5, MIN), NOW)
    assert b.retry_at == NOW - MIN + 8 * MIN


def test_cooldown_capped_at_30_min() -> None:
    b = breaker_state(fails(12, MIN), NOW)
    assert b.state == "open"
    assert b.retry_at == NOW - MIN + 30 * MIN


def test_half_open_after_cooldown() -> None:
    b = breaker_state(fails(3, 3 * MIN), NOW)
    assert b.state == "half_open" and b.retry_at == NOW - 3 * MIN + 2 * MIN


def test_empty_counts_as_failure() -> None:
    recent = [CallOutcome("empty", NOW - MIN), *fails(2, 2 * MIN)]
    assert breaker_state(recent, NOW).failures == 3


@pytest.mark.parametrize(
    ("state", "depth", "max_depth", "expected"),
    [
        ("closed", 0, 2000, BATCH),
        ("closed", 1990, 2000, 10),
        ("closed", 2500, 2000, 0),
        ("closed", 5, 0, BATCH),
        ("closed", None, 2000, 1),
        ("half_open", 0, 2000, 1),
        ("open", 0, 2000, 0),
    ],
)
def test_dispatch_limit(state: str, depth: int | None, max_depth: int, expected: int) -> None:
    b = Breaker(state, 0, None)  # type: ignore[arg-type]
    assert dispatch_limit(b, queue_depth=depth, max_depth=max_depth) == expected


def test_is_fresh_window() -> None:
    today = NOW.date()
    assert is_fresh(today, NOW)
    assert is_fresh(today - datetime.timedelta(days=1), NOW)
    assert not is_fresh(today - datetime.timedelta(days=2), NOW)
    assert not is_fresh(None, NOW)
