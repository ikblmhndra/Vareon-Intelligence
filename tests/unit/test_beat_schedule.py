"""`cti_worker.beat.build_beat_schedule` -- jadwal di-generate dari registry.

Sebelum Fase 10.B gak ada test sama sekali buat ini. Yang dikunci:
  - registry KOSONG = gagal keras (kasus nyata: image API/worker tanpa paket
    `cti-scrapers` -> `discover()` balik `{}` diam-diam -> beat naik "sehat"
    tapi gak pernah nge-fire scraper),
  - satu entri `scrape-<id>` per scraper aktif, di queue yang bener,
  - override control plane (Fase 9): `enabled=False` dilewatin, `schedule`
    override kepake.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from cti_scraper.health import expected_interval
from cti_scraper.queues import queue_for
from cti_scraper.registry import discover
from cti_worker import beat


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


def test_empty_registry_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})
    monkeypatch.setattr(beat, "discover", lambda: {})

    with pytest.raises(RuntimeError, match="registry scraper KOSONG"):
        beat.build_beat_schedule()


def test_one_entry_per_enabled_scraper_on_the_right_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})
    registry = discover()

    schedule = beat.build_beat_schedule()

    scrape = {k: v for k, v in schedule.items() if k.startswith("scrape-")}
    enabled = {sid: cls for sid, cls in registry.items() if cls.meta.enabled}
    assert set(scrape) == {f"scrape-{sid}" for sid in enabled}
    for sid, cls in enabled.items():
        entry = scrape[f"scrape-{sid}"]
        assert entry["task"] == "scrape.run"
        assert entry["args"] == (sid,)
        assert entry["options"]["queue"] == queue_for(cls.meta)
        assert set(entry["options"]) == {"queue", "expires"}
    # task periodik (Fase 7.8 + 9) ikut ada -- bukan cuma scraper
    for name in (
        "pir-check-p1-alerts",
        "ioc-decay-sweep",
        "ioc-enrich-pending",
        "scraper-health-digest",
    ):
        assert name in schedule


def test_control_plane_overrides_disable_and_reschedule(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = list(discover())
    off, moved = registry[0], registry[1]
    monkeypatch.setattr(
        beat,
        "_scraper_configs",
        lambda: {
            off: SimpleNamespace(enabled=False, schedule=None),
            moved: SimpleNamespace(enabled=True, schedule="7 3 * * *"),
        },
    )

    schedule = beat.build_beat_schedule()

    assert f"scrape-{off}" not in schedule
    cron = schedule[f"scrape-{moved}"]["schedule"]
    assert (cron.minute, cron.hour) == ({7}, {3})


# --- laporan periodik Fase 10.E ----------------------------------------


def _reports(monkeypatch: pytest.MonkeyPatch, offset: str | None = None) -> dict:
    from cti_core.config import get_settings

    if offset is not None:
        monkeypatch.setenv("WORKER__REPORT_UTC_OFFSET_HOURS", offset)
        get_settings.cache_clear()
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})
    return {k: v for k, v in beat.build_beat_schedule().items() if k.startswith("report-")}


def _cron(entry: dict) -> tuple[str, str, str]:
    c = entry["schedule"]
    return (str(c._orig_minute), str(c._orig_hour), str(c._orig_day_of_week))


def test_report_tasks_run_at_the_old_rundeck_local_times_converted_to_utc(monkeypatch) -> None:
    reports = _reports(monkeypatch)  # default: WIB (UTC+7)

    assert {k: v["task"] for k, v in reports.items()} == {
        "report-daily-counters": "report.daily_counters",
        "report-news-of-the-day": "report.news_of_the_day",
        "report-logbook": "report.logbook",
        "report-weekly-top-cve": "report.weekly_top_cve",
        "report-weekly-threat-actor-trend": "report.weekly_threat_actor_trend",
        "report-trending-cve": "report.trending_cve",
    }
    assert _cron(reports["report-daily-counters"]) == ("55", "16", "*")  # 23:55 WIB
    assert _cron(reports["report-news-of-the-day"]) == ("58", "16", "*")  # 23:58 WIB
    assert _cron(reports["report-logbook"]) == ("0", "0", "*")  # 07:00 WIB
    assert _cron(reports["report-weekly-top-cve"]) == ("1", "0", "0")  # Minggu 07:01 WIB
    assert _cron(reports["report-weekly-threat-actor-trend"]) == ("0", "6", "1")  # Senin 13:00 WIB
    assert _cron(reports["report-trending-cve"]) == ("5", "5,11,17,23", "*")  # 00/06/12/18 WIB


def test_report_times_follow_the_configured_offset(monkeypatch) -> None:
    reports = _reports(monkeypatch, offset="0")  # server produksi lama ternyata UTC

    assert _cron(reports["report-daily-counters"]) == ("55", "23", "*")
    assert _cron(reports["report-weekly-top-cve"]) == ("1", "7", "0")
    assert _cron(reports["report-weekly-threat-actor-trend"]) == ("0", "13", "1")  # Senin 13:00 UTC
    assert _cron(reports["report-trending-cve"]) == ("5", "0,6,12,18", "*")


def test_every_report_task_is_registered_with_celery_on_the_notify_queue(monkeypatch) -> None:
    from cti_worker.celery_app import app

    for entry in _reports(monkeypatch).values():
        assert entry["task"] in app.tasks, f"{entry['task']} tidak terdaftar di Celery"
        assert entry["options"] == {"queue": "notify"}


def test_the_weekly_trend_day_follows_the_offset_across_midnight(monkeypatch) -> None:
    """Senin 13:00 di UTC+14 = Minggu 23:00 UTC -- hari ikut bergeser, bukan cuma jamnya."""
    reports = _reports(monkeypatch, offset="14")

    assert _cron(reports["report-weekly-threat-actor-trend"]) == ("0", "23", "0")


def test_stale_scrape_ticks_expire_after_one_interval_so_a_recovering_worker_does_not_stampede(
    monkeypatch,
) -> None:
    """Latihan staging: worker mati -> tick menumpuk -> dieksekusi sekaligus saat pulih."""
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})
    scrape = {k: v for k, v in beat.build_beat_schedule().items() if k.startswith("scrape-")}

    for key, entry in scrape.items():
        cron = discover()[key.removeprefix("scrape-")].meta.schedule
        assert entry["options"]["expires"] == int(expected_interval(cron).total_seconds())
    # nilai konkret: tiap 15 menit = 900 dtk, per jam = 3600 dtk
    assert beat._tick_expiry_s("*/15 * * * *") == 900
    assert beat._tick_expiry_s("46 * * * *") == 3600
    assert beat._tick_expiry_s("* * * * *") == 60
    assert beat._tick_expiry_s("0 6 * * *") == 86400


def test_a_schedule_override_changes_the_expiry_with_it(monkeypatch) -> None:
    from types import SimpleNamespace

    sid = next(iter(discover()))
    override = SimpleNamespace(enabled=True, schedule="*/10 * * * *")
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {sid: override})

    entry = beat.build_beat_schedule()[f"scrape-{sid}"]

    assert entry["options"]["expires"] == 600


def test_periodic_report_tasks_never_expire(monkeypatch) -> None:
    """Laporan telat lebih baik daripada hilang -- hanya tick scrape yang boleh dibuang."""
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})
    schedule = beat.build_beat_schedule()

    for name, entry in schedule.items():
        if not name.startswith("scrape-"):
            assert "expires" not in entry["options"], name


# --- recap mingguan (#21, PR 2) -----------------------------------------


def test_weekly_recap_runs_monday_0015_utc_on_the_maintenance_queue(monkeypatch) -> None:
    """Senin 00:15 UTC = 07:15 WIB. Pekan Senin-Minggu (tanggal UTC) baru utuh setelah Minggunya
    lewat di UTC: 00:15 WIB (= Minggu 17:15 UTC) akan kehilangan Minggu 17:00-24:00 UTC."""
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})

    entry = beat.build_beat_schedule()["recap-generate-weekly"]

    assert entry["task"] == "recap.generate_weekly"
    assert _cron(entry) == ("15", "0", "1")  # menit, jam, hari-dalam-pekan (1 = Senin di cron)
    cron = entry["schedule"]
    assert (cron.minute, cron.hour, cron.day_of_week) == ({15}, {0}, {1})
    assert entry["options"] == {"queue": "maintenance"}


def test_the_schedule_does_not_depend_on_the_report_utc_offset(monkeypatch) -> None:
    """Jam recap adalah UTC murni (bukan jam lokal): mengubah `WORKER__REPORT_UTC_OFFSET_HOURS`
    menggeser laporan Telegram, bukan recap."""
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})
    from cti_core.config import get_settings

    monkeypatch.setenv("WORKER__REPORT_UTC_OFFSET_HOURS", "0")
    get_settings.cache_clear()

    assert _cron(beat.build_beat_schedule()["recap-generate-weekly"]) == ("15", "0", "1")


def test_the_daily_recap_is_no_longer_scheduled(monkeypatch) -> None:
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})

    schedule = beat.build_beat_schedule()

    assert "recap-generate-daily" not in schedule
    assert [e for e in schedule.values() if e["task"] == "recap.generate_daily"] == []


def test_the_weekly_recap_task_is_registered_and_the_daily_task_is_gone() -> None:
    from cti_worker.celery_app import app

    assert "recap.generate_weekly" in app.tasks
    assert "recap.generate_daily" not in app.tasks


# --- newsletter bulanan (#22, PR 8) ---------------------------------------------------------------


def test_the_newsletter_is_prepared_every_weekday_at_0200_utc_on_the_maintenance_queue(
    monkeypatch,
) -> None:
    """09:00 WIB = 02:00 UTC, Senin-Jumat (cron 1-5). Task-nya yang memutuskan apakah ini hari
    kerja pertama bulan itu (atau hari kejar); beat hanya mengetuknya tiap hari kerja."""
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})

    entry = beat.build_beat_schedule()["newsletter-prepare-monthly"]

    assert entry["task"] == "newsletter.prepare_monthly"
    cron = entry["schedule"]
    assert (cron.minute, cron.hour) == ({0}, {2})
    assert cron.day_of_week == {1, 2, 3, 4, 5}
    assert cron.day_of_month == set(range(1, 32)) and cron.month_of_year == set(range(1, 13))
    assert entry["options"] == {"queue": "maintenance"}


def test_the_newsletter_hour_follows_the_report_offset_but_stays_monday_to_friday(
    monkeypatch,
) -> None:
    """Offset 0 (server UTC): 09:00 UTC. Selama jamnya tidak melewati tengah malam UTC, rentang
    hari kerjanya tetap Senin-Jumat."""
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})
    from cti_core.config import get_settings

    monkeypatch.setenv("WORKER__REPORT_UTC_OFFSET_HOURS", "0")
    get_settings.cache_clear()

    cron = beat.build_beat_schedule()["newsletter-prepare-monthly"]["schedule"]

    assert (cron.minute, cron.hour, cron.day_of_week) == ({0}, {9}, {1, 2, 3, 4, 5})


def test_the_newsletter_task_is_registered_with_celery(monkeypatch) -> None:
    from cti_worker.celery_app import app

    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})
    entry = beat.build_beat_schedule()["newsletter-prepare-monthly"]

    assert entry["task"] in app.tasks
    assert "newsletter-prepare-monthly" in app.conf.beat_schedule


def test_the_newsletter_entry_never_expires(monkeypatch) -> None:
    """Telat lebih baik daripada hilang: edisi yang tertunda dikejar hari kerja berikutnya."""
    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})

    entry = beat.build_beat_schedule()["newsletter-prepare-monthly"]

    assert "expires" not in entry["options"]
