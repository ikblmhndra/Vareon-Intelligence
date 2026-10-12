"""Unit test jadwal bulanan newsletter (`cti_api.services.newsletter_schedule`, ROADMAP #22 PR 8):
hari kerja pertama bulan, kapan saran disiapkan sendiri (hari itu, hari kejar, tidak sesudah
jendela, tidak dua kali), dan `prepare_monthly` dengan DB serta LLM diganti stub. Yang menyentuh
Postgres ada di `tests/integration/test_newsletter_prepare_monthly.py`."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from cti_api.services import newsletter_schedule as schedule

D = datetime.date
UTC = datetime.UTC


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from cti_core.config import get_settings

    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- hari kerja pertama -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "month", "expected"),
    [
        (2026, 10, D(2026, 10, 1)),  # Kamis: tanggal 1 sendiri
        (2026, 6, D(2026, 6, 1)),  # Senin
        (2026, 8, D(2026, 8, 3)),  # tanggal 1 hari Sabtu: Senin 3
        (2026, 11, D(2026, 11, 2)),  # tanggal 1 hari Minggu: Senin 2 (edisi Oktober)
        (2026, 12, D(2026, 12, 1)),  # Selasa
        (2027, 1, D(2027, 1, 1)),  # Jumat, hari libur tapi hari libur tidak dilacak
        (2028, 1, D(2028, 1, 3)),  # pergantian tahun, 1 Jan 2028 hari Sabtu
        (2028, 10, D(2028, 10, 2)),  # 1 Okt 2028 hari Minggu
    ],
)
def test_first_weekday_is_the_first_monday_to_friday(year: int, month: int, expected: D) -> None:
    assert schedule.first_weekday(year, month) == expected


def test_first_weekday_is_always_a_weekday_within_the_first_three_days() -> None:
    for year in range(2025, 2032):
        for month in range(1, 13):
            first = schedule.first_weekday(year, month)
            assert first.weekday() < 5, (year, month)
            assert (first.year, first.month) == (year, month)
            assert first.day <= 3
            # tidak ada hari kerja yang terlewat sebelum itu
            assert all(D(year, month, d).weekday() >= 5 for d in range(1, first.day))


# --- kapan disiapkan --------------------------------------------------------------------------


def test_it_prepares_on_the_first_weekday_of_the_month() -> None:
    assert schedule.should_prepare(D(2026, 11, 2), has_suggestion_for_previous_month=False)
    assert schedule.should_prepare(D(2026, 10, 1), has_suggestion_for_previous_month=False)


def test_the_days_after_it_are_the_catch_up_until_the_window_closes() -> None:
    first = D(2026, 11, 2)
    for offset in range(0, schedule.PREPARE_WINDOW_DAYS + 1):
        day = first + datetime.timedelta(days=offset)
        assert schedule.should_prepare(day, has_suggestion_for_previous_month=False), day
    # `PREPARE_WINDOW_DAYS` hari sesudah hari kerja pertama masih boleh (Senin 9 Nov), sehari
    # lagi tidak: sesudah itu hanya rebuild dengan tangan.
    assert not schedule.should_prepare(D(2026, 11, 10), has_suggestion_for_previous_month=False)
    assert not schedule.should_prepare(D(2026, 11, 20), has_suggestion_for_previous_month=False)
    assert not schedule.should_prepare(D(2026, 11, 30), has_suggestion_for_previous_month=False)


def test_a_mid_month_deploy_does_not_build_a_month_that_was_already_sent() -> None:
    assert not schedule.should_prepare(D(2026, 10, 14), has_suggestion_for_previous_month=False)


def test_nothing_happens_before_the_first_weekday() -> None:
    """Minggu 1 Nov: beat tidak jalan akhir pekan, tapi fungsinya sendiri juga menolak."""
    assert not schedule.should_prepare(D(2026, 11, 1), has_suggestion_for_previous_month=False)
    assert not schedule.should_prepare(D(2026, 8, 1), has_suggestion_for_previous_month=False)


def test_an_existing_suggestion_makes_every_later_run_a_no_op() -> None:
    first = D(2026, 11, 2)
    for offset in range(0, 31):
        day = first + datetime.timedelta(days=offset)
        assert not schedule.should_prepare(day, has_suggestion_for_previous_month=True), day


def test_the_year_changes_without_a_special_case() -> None:
    """Edisi Desember disiapkan Jumat 1 Jan 2027, kejarnya Senin 4 dan seterusnya."""
    for day in (D(2027, 1, 1), D(2027, 1, 4), D(2027, 1, 8)):
        assert schedule.should_prepare(day, has_suggestion_for_previous_month=False)
    assert not schedule.should_prepare(D(2027, 1, 11), has_suggestion_for_previous_month=False)


# --- prepare_monthly --------------------------------------------------------------------------


class _FakeRepo:
    """`AsyncNewsletterRepo` palsu: hanya `get_suggestion`, dan mencatat jendela yang ditanya."""

    existing: Any = None
    asked: list[tuple[D, D]] = []  # noqa: RUF012 - state kelas sengaja, direset tiap test

    def __init__(self, session: Any) -> None:
        pass

    async def get_suggestion(self, period_start: D, period_end: D) -> Any:
        type(self).asked.append((period_start, period_end))
        return type(self).existing


def _row(error: str | None = None, **extra: Any) -> SimpleNamespace:
    """Baris saran palsu: `summary_meta.error` menentukan apakah ringkasannya perlu diulang."""
    fields: dict[str, Any] = {
        "id": 7,
        "items": [{"article_id": 1}],
        "summary_text": "Ringkasan." if error is None else "",
        "summary_meta": {"error": error},
    }
    return SimpleNamespace(**{**fields, **extra})


@pytest.fixture
def build(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    _FakeRepo.existing, _FakeRepo.asked = None, []
    built = AsyncMock(return_value=_row())
    monkeypatch.setattr(schedule, "AsyncNewsletterRepo", _FakeRepo)
    monkeypatch.setattr(schedule.newsletter_suggestion, "build_suggestion", built)
    return built


@pytest.fixture
def refresh(monkeypatch: pytest.MonkeyPatch, build: AsyncMock) -> AsyncMock:
    """`refresh_summary` palsu: mengembalikan baris dengan ringkasan yang sudah terisi."""
    refreshed = AsyncMock(return_value=_row())
    monkeypatch.setattr(schedule.newsletter_suggestion, "refresh_summary", refreshed)
    return refreshed


async def test_on_the_first_weekday_it_builds_the_previous_month(build: AsyncMock) -> None:
    now = datetime.datetime(2026, 11, 2, 2, 0, tzinfo=UTC)  # Senin 09:00 WIB

    result = await schedule.prepare_monthly("SESSION", now)  # type: ignore[arg-type]

    build.assert_awaited_once_with("SESSION", D(2026, 10, 1), D(2026, 10, 31))
    assert _FakeRepo.asked == [(D(2026, 10, 1), D(2026, 10, 31))]
    assert result == {
        "prepared": True,
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "suggestion_id": 7,
        "items": 1,
        "summary": True,
        "summary_error": None,
    }


async def test_the_second_run_finds_the_suggestion_and_does_nothing(build: AsyncMock) -> None:
    _FakeRepo.existing = _row()
    tuesday = datetime.datetime(2026, 11, 3, 2, 0, tzinfo=UTC)

    result = await schedule.prepare_monthly("SESSION", tuesday)  # type: ignore[arg-type]

    build.assert_not_awaited()
    assert result == {"prepared": False, "period_start": "2026-10-01"}


async def test_a_worker_that_was_down_catches_up_inside_the_window(build: AsyncMock) -> None:
    thursday = datetime.datetime(2026, 11, 5, 2, 0, tzinfo=UTC)

    result = await schedule.prepare_monthly("SESSION", thursday)  # type: ignore[arg-type]

    build.assert_awaited_once()
    assert result["prepared"] is True


async def test_after_the_window_the_task_returns_at_once_without_building(
    build: AsyncMock,
) -> None:
    """Hari ke-12: tidak ada saran untuk Oktober pun, tidak dibuat (hanya rebuild tangan)."""
    midmonth = datetime.datetime(2026, 11, 12, 2, 0, tzinfo=UTC)

    result = await schedule.prepare_monthly("SESSION", midmonth)  # type: ignore[arg-type]

    build.assert_not_awaited()
    assert result["prepared"] is False


async def test_today_is_the_local_date_not_the_utc_date(build: AsyncMock) -> None:
    """31 Okt 20:00 UTC = 1 Nov 03:00 WIB (Minggu): sudah November di tim, jendelanya Oktober
    (sama dengan `default_period`), tapi bukan hari kerja pertama. 1 Nov 20:00 UTC = Senin 2 Nov
    03:00 WIB: hari kerja pertama, padahal tanggal UTC-nya masih Minggu."""
    sunday_night = datetime.datetime(2026, 10, 31, 20, 0, tzinfo=UTC)
    monday_early = datetime.datetime(2026, 11, 1, 20, 0, tzinfo=UTC)

    skipped = await schedule.prepare_monthly("S", sunday_night)  # type: ignore[arg-type]
    built = await schedule.prepare_monthly("S", monday_early)  # type: ignore[arg-type]

    assert skipped["prepared"] is False
    assert built["prepared"] is True
    build.assert_awaited_once_with("S", D(2026, 10, 1), D(2026, 10, 31))


async def test_an_empty_summary_is_reported_as_such(build: AsyncMock) -> None:
    build.return_value = _row(items=[], summary_text="", id=8)

    result = await schedule.prepare_monthly(
        "S",  # type: ignore[arg-type]
        datetime.datetime(2026, 11, 2, 2, 0, tzinfo=UTC),
    )

    assert result["summary"] is False and result["items"] == 0


async def test_a_failed_summary_still_counts_as_prepared_and_reports_the_error(
    build: AsyncMock,
) -> None:
    """Ranking tersimpan (`prepared`), ringkasannya kosong dan alasannya ada di hasil task."""
    build.return_value = _row("RuntimeError: gateway down")
    now = datetime.datetime(2026, 11, 2, 2, 0, tzinfo=UTC)

    result = await schedule.prepare_monthly("S", now)  # type: ignore[arg-type]

    assert result["prepared"] is True and result["items"] == 1
    assert result["summary"] is False
    assert result["summary_error"] == "RuntimeError: gateway down"


# --- ringkasan yang gagal dikejar ---------------------------------------------------------------


def test_the_summary_is_retried_only_inside_the_catch_up_window_and_only_after_an_error() -> None:
    first = D(2026, 11, 2)
    for offset in range(0, schedule.PREPARE_WINDOW_DAYS + 1):
        day = first + datetime.timedelta(days=offset)
        assert schedule.should_retry_summary(day, suggestion_has_summary_error=True), day
        assert not schedule.should_retry_summary(day, suggestion_has_summary_error=False), day
    assert not schedule.should_retry_summary(D(2026, 11, 10), suggestion_has_summary_error=True)
    assert not schedule.should_retry_summary(D(2026, 11, 1), suggestion_has_summary_error=True)


async def test_a_suggestion_whose_summary_failed_gets_only_the_summary_redone(
    build: AsyncMock, refresh: AsyncMock
) -> None:
    failed = _row("RuntimeError: gateway down")
    _FakeRepo.existing = failed
    tuesday = datetime.datetime(2026, 11, 3, 2, 0, tzinfo=UTC)

    result = await schedule.prepare_monthly("S", tuesday)  # type: ignore[arg-type]

    refresh.assert_awaited_once_with("S", failed)
    build.assert_not_awaited()  # tidak merangking ulang
    assert result == {
        "prepared": False,
        "summary_retried": True,
        "period_start": "2026-10-01",
        "suggestion_id": 7,
        "summary": True,
        "summary_error": None,
    }


async def test_a_retry_that_fails_again_reports_the_new_error_and_the_next_day_tries_again(
    build: AsyncMock, refresh: AsyncMock
) -> None:
    _FakeRepo.existing = _row("RuntimeError: gateway down")
    refresh.return_value = _row("TimeoutError")

    first = await schedule.prepare_monthly(
        "S",  # type: ignore[arg-type]
        datetime.datetime(2026, 11, 3, 2, 0, tzinfo=UTC),
    )
    second = await schedule.prepare_monthly(
        "S",  # type: ignore[arg-type]
        datetime.datetime(2026, 11, 4, 2, 0, tzinfo=UTC),
    )

    assert first["summary_error"] == second["summary_error"] == "TimeoutError"
    assert refresh.await_count == 2


@pytest.mark.parametrize(
    ("existing", "day"),
    [
        (_row(), 3),  # ringkasan sehat: tidak ada LLM lagi
        (_row("RuntimeError: x"), 10),  # sesudah jendela kejar
        (_row(summary_meta={}), 3),  # baris dari sebelum ringkasan ada: bukan kegagalan
    ],
)
async def test_nothing_is_retried_when_the_summary_is_fine_or_the_window_is_over(
    build: AsyncMock, refresh: AsyncMock, existing: SimpleNamespace, day: int
) -> None:
    _FakeRepo.existing = existing

    result = await schedule.prepare_monthly(
        "S",  # type: ignore[arg-type]
        datetime.datetime(2026, 11, day, 2, 0, tzinfo=UTC),
    )

    assert result == {"prepared": False, "period_start": "2026-10-01"}
    build.assert_not_awaited()
    refresh.assert_not_awaited()
