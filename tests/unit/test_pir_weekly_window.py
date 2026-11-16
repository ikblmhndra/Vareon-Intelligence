"""Unit test `weekly_window` -- jendela minggu untuk grafik coverage PIR (0.8.15)."""

from __future__ import annotations

from datetime import date

from cti_core.db.repositories.pir import weekly_window

TODAY = date(2026, 11, 8)  # Minggu; Senin minggu itu = 2026-11-02


def test_window_from_start_date() -> None:
    assert weekly_window(date(2026, 9, 1), None, TODAY, 26) == (date(2026, 8, 31), TODAY)


def test_window_capped_by_weeks() -> None:
    assert weekly_window(date(2025, 1, 1), None, TODAY, 4) == (date(2026, 10, 12), TODAY)


def test_window_no_start() -> None:
    assert weekly_window(None, None, TODAY, 2) == (date(2026, 10, 26), TODAY)


def test_window_past_end() -> None:
    assert weekly_window(date(2026, 9, 1), date(2026, 9, 30), TODAY, 26) == (
        date(2026, 8, 31),
        date(2026, 9, 30),
    )


def test_window_future_start() -> None:
    assert weekly_window(date(2026, 12, 1), None, TODAY, 26) is None
