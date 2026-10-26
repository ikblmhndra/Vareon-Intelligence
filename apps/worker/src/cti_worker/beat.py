"""Beat schedule DI-GENERATE dari registry scraper (plan §4: "tiap scraper
membawa schedule-nya sendiri, tidak ada file jadwal terpusat untuk
diedit") -- BUKAN dict statis yang di-maintain manual. Tambah scraper baru
= tambah satu file di `scrapers/`, jadwalnya otomatis muncul di sini pas
beat restart, gak ada tempat lain yang perlu disentuh.

`ScraperMeta.schedule` udah cron 5-field standar (`spread()`, Fase 3,
motong field MENIT `*/N` biar N scraper gak nembak bareng) -- konversi ke
`celery.schedules.crontab` itu pemetaan LANGSUNG per-field, bukan translasi
yang perlu library tambahan.

6 entri lama di `_PERIODIC_SCHEDULE` (Fase 7.8, `tasks/periodic.py`) --
port 5 loop `ScraperNewsWeb/app/main.py`. Jam IOC decay (04:00)/daily
recap (06:00, sekarang diganti recap MINGGUAN Senin 00:15 UTC, #21)/CVE enrichment (tiap 3 jam)
HARDCODED port apa adanya dari `_seconds_until_04h_utc()`/`_seconds_until_06h_utc()`/
`_seconds_until_next_3h()` lama (gak pernah env-configurable di kode
lama, jadi gak dijadiin `Settings` field juga di sini). PIR
P1/all-interval PAKAI `Settings.worker` (lihat docstring
`cti_api.services.pir_alert` soal kenapa dipecah 2 entry) -- BUKAN
`get_settings()` dipanggil pas modul ini di-import (`build_beat_schedule()`
dipanggil sekali di `celery_app.py`, env harus udah siap saat itu, sama
kayak semua env lain yang dibaca modul ini). +3 entri Fase 9: purge
`scraper_items`/`scraper_seen` (jam 03:00 -- sebelum IOC decay 04:00, gak
ada padanan lama, dua tabel ini gak pernah ada di skema Mongo) +
`scraper-health-digest` (`Settings.worker.scraper_health_sweep_interval_min`,
default 30 menit -- SATU pesan Telegram konsolidasi, `cti_scraper.health.
summarize_fleet_health()`, gak ngirim apa-apa kalau semua scraper `ok`).

`_scraper_configs()` (Fase 9) -- SATU query `ScraperConfig` (control
plane) dibaca pas `build_beat_schedule()` jalan, bukan per-scraper.
`enabled=False`/`schedule` override kepake pas beat DI-BUILD (worker
start), BUKAN dinamis lintas-tick -- gak ada scheduler yang polling DB
tiap tick di codebase ini, ganti override lewat API efeknya baru
keliatan abis restart worker/beat berikutnya. `Runner.execute()`
(`cti_scraper`) TETAP cek ulang `enabled` pas eksekusi beneran -- jaring
pengaman kalau override berubah di ANTARA beat-build dan tick
berikutnya, atau kalau task-nya dipicu manual (trigger API) di luar
beat sama sekali."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from celery.schedules import crontab
from cti_core.config import get_settings
from cti_scraper.health import expected_interval
from cti_scraper.queues import queue_for
from cti_scraper.registry import discover
from cti_scraper.supersede import effective_enabled

from cti_worker.queues import QUEUE_ENRICH, QUEUE_MAINTENANCE, QUEUE_NOTIFY
from cti_worker.reports.timeutil import local_to_utc_cron

if TYPE_CHECKING:
    from cti_core.db.models.scraper import ScraperConfig

_RE_ZERO_STEP = re.compile(r"^0/(\d+)$")


def _normalize_field(field: str) -> str:
    """POSIX cron terima `0/N` ("mulai dari 0, tiap N unit", sama artinya
    `*/N` buat field APA PUN -- 0 selalu nilai minimum tiap field cron).
    Parser `celery.schedules.crontab` gak nerima bentuk `0/N`, cuma
    `*/N` -- ketauan LIVE: scraper `eset` (jadwal dipulihin dari Rundeck,
    Fase 4 `import_rundeck.py`) punya jam `"0/1"`. Ganti ke `*/N`, hasil
    match SAMA PERSIS (kedua bentuk = "tiap N unit mulai dari awal field").
    `N/M` non-zero-start (mis. "5/10") DIBIARIN apa adanya -- gak ada
    kasus itu di 83 scraper aktif sekarang, dan konversi yang bener butuh
    tau batas maksimum field ini (beda-beda per field), bukan sesuatu yang
    aman ditebak generik."""
    m = _RE_ZERO_STEP.match(field)
    return f"*/{m.group(1)}" if m else field


def _cron_to_crontab(cron: str) -> crontab:
    minute, hour, day_of_month, month_of_year, day_of_week = cron.split()
    return crontab(
        minute=_normalize_field(minute),
        hour=_normalize_field(hour),
        day_of_month=_normalize_field(day_of_month),
        month_of_year=_normalize_field(month_of_year),
        day_of_week=_normalize_field(day_of_week),
    )


def _report_schedule(offset: int) -> dict[str, dict[str, object]]:
    """Laporan periodik Fase 10.E. Jam di bawah = jam LOKAL Rundeck lama (job
    "News Counter" 23:55, trendingNewsToday 23:58, Logbook 07:00, Top Cve Minggu
    07:01, Twitter CVE Trending tiap 6 jam, tren threat actor Senin 13:00 -- yang terakhir
    dipilih user, bukan jadwal Rundeck lama); `local_to_utc_cron` menggesernya ke UTC sesuai
    `WorkerSettings.report_utc_offset_hours`."""
    trending_hours = ",".join(str(h) for h in sorted({(h - offset) % 24 for h in (0, 6, 12, 18)}))
    return {
        "report-daily-counters": {
            "task": "report.daily_counters",
            "schedule": crontab(**local_to_utc_cron(23, 55, offset)),
            "options": {"queue": QUEUE_NOTIFY},
        },
        "report-news-of-the-day": {
            "task": "report.news_of_the_day",
            "schedule": crontab(**local_to_utc_cron(23, 58, offset)),
            "options": {"queue": QUEUE_NOTIFY},
        },
        "report-logbook": {
            "task": "report.logbook",
            "schedule": crontab(**local_to_utc_cron(7, 0, offset)),
            "options": {"queue": QUEUE_NOTIFY},
        },
        "report-weekly-top-cve": {
            "task": "report.weekly_top_cve",
            "schedule": crontab(**local_to_utc_cron(7, 1, offset, weekday=6)),  # Minggu
            "options": {"queue": QUEUE_NOTIFY},
        },
        "report-weekly-threat-actor-trend": {
            "task": "report.weekly_threat_actor_trend",
            "schedule": crontab(**local_to_utc_cron(13, 0, offset, weekday=0)),  # Senin
            "options": {"queue": QUEUE_NOTIFY},
        },
        "report-trending-cve": {
            "task": "report.trending_cve",
            # menit 5: pengumpulan mention (`trending_cve`, tiap 15 menit di menit 0)
            # sudah selesai; kode lama melapor di run menit-0 itu sendiri.
            "schedule": crontab(hour=trending_hours, minute=5),
            "options": {"queue": QUEUE_NOTIFY},
        },
    }


def _periodic_schedule() -> dict[str, dict[str, object]]:
    w = get_settings().worker
    offset = w.report_utc_offset_hours
    return {
        "pir-check-p1-alerts": {
            "task": "pir.check_p1_alerts",
            "schedule": crontab(minute=f"*/{w.pir_p1_alert_interval_min}"),
            "options": {"queue": QUEUE_NOTIFY},
        },
        "pir-check-all-alerts": {
            "task": "pir.check_all_alerts",
            "schedule": crontab(minute=f"*/{w.pir_alert_interval_min}"),
            "options": {"queue": QUEUE_NOTIFY},
        },
        "attack-sync-check": {
            "task": "attack.sync_check",
            "schedule": crontab(hour=5, minute=0),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "ioc-decay-sweep": {
            "task": "ioc.decay_sweep",
            "schedule": crontab(hour=4, minute=0),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "ioc-enrich-pending": {
            "task": "ioc.enrich_pending",
            # Tiap 15 menit; jatah per jam (bukan jadwal ini) yang membatasi panggilan ke provider,
            # dan task-nya no-op kalau tak ada kunci provider yang terisi.
            "schedule": crontab(minute="*/15"),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "recap-generate-weekly": {
            "task": "recap.generate_weekly",
            # Senin 00:15 UTC = 07:15 WIB: pekan Senin-Minggu (tanggal UTC) baru utuh setelah
            # Minggunya lewat di UTC, jadi 00:15 WIB (= Minggu 17:15 UTC) akan kehilangan Minggu
            # 17:00-24:00 UTC. Hardcoded: tidak ada setting `RECAP__SCHEDULE` (#21), yang bisa
            # diubah cuma lewat kode, dan entri ini aditif (rollback = revert + restart beat).
            "schedule": crontab(day_of_week=1, hour=0, minute=15),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "newsletter-prepare-monthly": {
            "task": "newsletter.prepare_monthly",
            # Tiap hari kerja 09:00 WIB (02:00 UTC). `local_to_utc_cron` hanya menerima satu hari,
            # jadi jam-menitnya saja yang dipakai dan Senin-Jumat ditulis langsung; 09:00 WIB tidak
            # melewati tengah malam UTC (selama offset laporan di antara -14 dan +9), jadi rentang
            # harinya tidak bergeser. Task-nya yang memutuskan apakah ini hari kerja pertama
            # bulan itu atau hari kejar (`newsletter_schedule.should_prepare`).
            "schedule": crontab(
                day_of_week="1-5", **local_to_utc_cron(9, 0, w.report_utc_offset_hours)
            ),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "cve-enrichment-sweep": {
            "task": "cve.enrichment_sweep",
            "schedule": crontab(hour="*/3", minute=0),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "cve-mirror-sync": {
            "task": "cve.mirror_sync",
            "schedule": crontab(minute="*/5"),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "cve-mirror-purge": {
            "task": "cve.mirror_purge",
            "schedule": crontab(hour=3, minute=30),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "enrich-auto-replay": {
            "task": "enrich.auto_replay",
            "schedule": crontab(minute="*/10"),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "llm-purge-calls": {
            "task": "llm.purge_calls",
            "schedule": crontab(hour=3, minute=40),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "relevance-train": {
            "task": "relevance.train",
            # Minggu 02:00 lokal; `weekday` memakai konvensi Python di `local_to_utc_cron`
            # (0=Senin..6=Minggu), jadi Minggu = 6 (sama seperti recap di `_report_schedule`).
            "schedule": crontab(**local_to_utc_cron(2, 0, offset, weekday=6)),
            "options": {"queue": QUEUE_ENRICH},
        },
        "relevance-evaluate": {
            "task": "relevance.evaluate",
            "schedule": crontab(minute=7),
            "options": {"queue": QUEUE_ENRICH},
        },
        "story-purge-empty": {
            "task": "story.purge_empty",
            "schedule": crontab(hour=3, minute=50),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "scraper-purge-expired-items": {
            "task": "scraper.purge_expired_items",
            "schedule": crontab(hour=3, minute=0),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "scraper-purge-expired-seen": {
            "task": "scraper.purge_expired_seen",
            "schedule": crontab(hour=3, minute=15),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "scraper-purge-old-runs": {
            "task": "scraper.purge_old_runs",
            "schedule": crontab(hour=3, minute=5),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "scraper-reap-stale-runs": {
            "task": "scraper.reap_stale_runs",
            "schedule": crontab(minute="*/30"),
            "options": {"queue": QUEUE_MAINTENANCE},
        },
        "scraper-health-digest": {
            "task": "scraper.health_digest",
            "schedule": crontab(minute=f"*/{w.scraper_health_sweep_interval_min}"),
            "options": {"queue": QUEUE_NOTIFY},
        },
        **_report_schedule(w.report_utc_offset_hours),
    }


def _scraper_configs() -> dict[str, ScraperConfig]:
    """`ScraperConfig` (Fase 9, control plane) -- dibaca SEKALI di sini,
    bukan per-scraper, biar cuma satu query. Kalau DB belum kebentuk pas
    beat pertama kali boot (mis. urutan startup Compose), gagal DIAM-DIAM
    balik ke `{}` (semua scraper pakai default kode) -- gak boleh bikin
    seluruh beat gagal start cuma gara-gara satu tabel override belum
    ke-migrate."""
    try:
        from cti_core.db.engine import sync_session
        from cti_core.db.repositories.scraper import ScraperConfigRepo

        with sync_session() as session:
            return dict(ScraperConfigRepo(session).get_all())
    except Exception:
        return {}


def build_beat_schedule() -> dict[str, dict[str, object]]:
    schedule: dict[str, dict[str, object]] = dict(_periodic_schedule())
    configs = _scraper_configs()
    registry = discover()
    if not registry:
        # `discover()` balik `{}` diam-diam kalau paket `cti_scrapers` gak
        # ke-install -- beat naik "sehat" tapi TIDAK PERNAH nge-fire scraper
        # apa pun. Kegagalan senyap kayak gini yang gak boleh terjadi lagi.
        raise RuntimeError(
            "registry scraper KOSONG -- paket `cti-scrapers` gak ter-install di image "
            "ini? Beat menolak start tanpa scraper."
        )
    for scraper_id, cls in registry.items():
        meta = cls.meta
        config = configs.get(scraper_id)

        # Control plane / meta DAN tidak digantikan mirror CVE (`cti_scraper.supersede`).
        if not effective_enabled(meta, config):
            continue

        # Override CUMA kepake pas beat DI-BUILD (proses worker start) --
        # ganti `ScraperConfig.schedule` lewat control plane API efeknya
        # baru keliatan abis worker/beat restart berikutnya, BUKAN
        # langsung. Dokumentasikan ini di API, jangan janji "langsung
        # kepake" -- gak ada scheduler dinamis (polling DB tiap tick) di
        # codebase ini, dan gak ada kebutuhan nyata yang minta itu sekarang.
        cron = config.schedule if config is not None and config.schedule else meta.schedule

        schedule[f"scrape-{scraper_id}"] = {
            "task": "scrape.run",
            "schedule": _cron_to_crontab(cron),
            "args": (scraper_id,),
            "options": {"queue": queue_for(meta), "expires": _tick_expiry_s(cron)},
        }
    return schedule


def _tick_expiry_s(cron: str) -> int:
    """Kedaluwarsa satu tick scrape = SATU interval jadwalnya (`expected_interval` sudah menjamin
    minimal 60 dtk).

    Ketemu di latihan staging 10.G: `worker-browser` mati 6 menit, beat terus mengirim tick tiap
    menit, dan begitu worker nyala SEMUA tick yang menumpuk dieksekusi sekaligus. Di produksi
    itu berarti worker mati 24 jam = ~24 run per scraper per jam-nya x 25 scraper Chromium
    sekaligus begitu pulih (thundering herd, dan ban dari situs sumber). Tick yang sudah lewat
    satu interval tidak berguna: tick berikutnya sudah/segera datang -- lebih baik dibuang.
    Task periodik LAIN (laporan harian, dst) sengaja tidak kedaluwarsa: telat lebih baik
    daripada hilang."""
    return int(expected_interval(cron).total_seconds())
