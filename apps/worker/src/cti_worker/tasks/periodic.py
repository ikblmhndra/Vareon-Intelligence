"""6 task periodic (Celery beat) -- Fase 7.8, port dari `ScraperNewsWeb/
app/main.py`'s 5 background loop `asyncio.create_task` (`_pir_alert_loop`
dkk), SEMUA jalan di DALAM proses uvicorn -- >1 worker uvicorn gandain
loop N kali, salah satu pemicu revamp ini (lihat plan). 5 loop -> 6 task
di sini karena `_pir_alert_loop` (satu loop, dua interval P1/P2+ internal)
dipecah jadi 2 beat entry terpisah biar STATELESS -- lihat docstring
`cti_api.services.pir_alert` buat alasan lengkapnya.

Beat (`cti_worker.beat`) yang jadwalin (crontab), task di sini yang
eksekusi -- TANPA state in-process (`_pir_check_since`, `p1_tick`/
`all_tick`, dkk versi lama gak ada padanannya, lihat docstring
`pir_alert`).

Semua manggil LANGSUNG fungsi async `cti_api.services.*` yang UDAH ADA
(session-first, `AsyncSession`) lewat `asyncio.run()` -- Celery task itu
sendiri fungsi SYNC biasa (beda dari `tasks/enrich.py` yang emang native
sync lewat `sync_session()`+`cti_enrich.pipeline`). Kenapa gak ditulis
ulang jadi sync: logic-nya (CVE lookup HTTP, recap LLM, PIR matching,
ATT&CK sync) UDAH ada+teruji di `cti_api.services` (dipakai endpoint API
juga) -- nulis ulang bakal DUPLIKAT logic bisnis, bukan cuma beda gaya
kode (lihat komentar dependency `cti-api` di `pyproject.toml`).

`cti_alerts.telegram.send_alert()` (dipanggil PIR alert) `asyncio.run()`
DI DALAMNYA sendiri -- nested event loop = `RuntimeError`. Makanya kirim
alert SELALU di LUAR `asyncio.run()` task ini: fase "kumpulin match" (di
dalam asyncio.run) dan fase "kirim Telegram" (di luar, sync biasa) SENGAJA
dipisah dua langkah, lihat `_check_pir_alerts`.

Gak ada retry otomatis di task-task ini (beda dari `scrape.run`) --
sama filosofi kayak versi lama: gagal sekali, tick berikutnya (jadwal
cron tetap) coba lagi sendiri, gak perlu retry-backoff eksplisit buat
loop periodic. CVE enrichment tetap PER-LOOKUP try/except (port apa
adanya dari `_cve_enrichment_loop` -- CISA gagal jangan sampe EPSS ikut
gak jalan), tapi task lain DIBIARIN gagal keras (`cti_alerts.telegram`'s
docstring: "gak nelan exception... Caller yang mutusin mau retry/log,
bukan modul ini yang diam-diam nutupin") -- kegagalan visible di log
Celery, bukan `print()` yang ketelen."""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import Coroutine
from typing import Any

import structlog

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_MAINTENANCE, QUEUE_NOTIFY

log = structlog.get_logger()


def _run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """`asyncio.run()` bikin event loop BARU tiap panggilan -- tapi
    `cti_core.db.engine`'s async engine/sessionmaker `@lru_cache`
    SEKALI per PROSES (cocok buat FastAPI: satu event loop uvicorn yang
    idup terus). Di worker Celery yang manggil `asyncio.run()` BERULANG
    (task beda, tick beda, SATU proses worker yang sama), engine lama
    nyangkut ke pool koneksi asyncpg yang keiket ke loop yang UDAH
    KETUTUP begitu `asyncio.run()` sebelumnya kelar -- KETEMU LIVE (bukan
    dugaan): `cve.enrichment_sweep` gagal `RuntimeError: Event loop is
    closed` / "attached to a different loop" pas dispatch manual abis
    `ioc.decay_sweep` jalan duluan di worker proses yang sama.

    Fix: `reset_engines()` (SUDAH ada, dipakai fixture test buat alasan
    serupa) abis TIAP `asyncio.run()` kelar -- cache di-clear, panggilan
    berikutnya (task apa pun, tick apa pun) bikin engine BARU di dalam
    loop barunya sendiri. `finally` -- reset tetap jalan walau task di
    atasnya raise."""
    from cti_core.db.engine import reset_engines

    try:
        return asyncio.run(coro)
    finally:
        reset_engines()


# ── PIR alert ──────────────────────────────────────────────────────────────


async def _collect_pir_matches(
    *, since_minutes: int, only_priority: str | None = None, exclude_priority: str | None = None
) -> list[dict[str, Any]]:
    from cti_api.services.pir_alert import check_new_articles_vs_pirs
    from cti_core.db.engine import async_session

    since = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=since_minutes)
    async with async_session() as session:
        return await check_new_articles_vs_pirs(
            session, since=since, only_priority=only_priority, exclude_priority=exclude_priority
        )


def _check_pir_alerts(
    *, since_minutes: int, only_priority: str | None = None, exclude_priority: str | None = None
) -> int:
    from cti_alerts.telegram import send_alert
    from cti_api.services.pir_alert import format_pir_alert

    matches = _run_async(
        _collect_pir_matches(
            since_minutes=since_minutes,
            only_priority=only_priority,
            exclude_priority=exclude_priority,
        )
    )
    for m in matches:
        send_alert("pir", format_pir_alert(m["pir"], m["articles"]))
    return len(matches)


@app.task(bind=True, name="pir.check_p1_alerts", queue=QUEUE_NOTIFY)
def check_p1_alerts(self: Any) -> dict[str, object]:
    from cti_core.config import get_settings

    interval = get_settings().worker.pir_p1_alert_interval_min
    matched = _check_pir_alerts(since_minutes=interval, only_priority="P1")
    return {"pir_matched": matched}


@app.task(bind=True, name="pir.check_all_alerts", queue=QUEUE_NOTIFY)
def check_all_alerts(self: Any) -> dict[str, object]:
    from cti_core.config import get_settings

    interval = get_settings().worker.pir_alert_interval_min
    matched = _check_pir_alerts(since_minutes=interval, exclude_priority="P1")
    return {"pir_matched": matched}


# ── ATT&CK sync ──────────────────────────────────────────────────────────────


async def _run_attack_sync_check(*, interval_days: int) -> list[dict[str, Any]] | None:
    from cti_api.services.attack_sync_check import sync_if_needed
    from cti_core.db.engine import async_session

    async with async_session() as session:
        return await sync_if_needed(session, interval_days=interval_days)


@app.task(bind=True, name="attack.sync_check", queue=QUEUE_MAINTENANCE)
def attack_sync_check(self: Any) -> dict[str, object]:
    from cti_core.config import get_settings

    interval_days = get_settings().worker.attack_sync_interval_days
    results = _run_async(_run_attack_sync_check(interval_days=interval_days))
    if results is None:
        return {"synced": False}
    return {"synced": True, "domains": len(results)}


# ── IOC decay ──────────────────────────────────────────────────────────────


async def _run_ioc_decay_sweep() -> dict[str, Any]:
    from cti_api.services.ioc_decay import decay_sweep
    from cti_core.db.engine import async_session

    async with async_session() as session:
        return await decay_sweep(session)


@app.task(bind=True, name="ioc.decay_sweep", queue=QUEUE_MAINTENANCE)
def ioc_decay_sweep(self: Any) -> dict[str, object]:
    return _run_async(_run_ioc_decay_sweep())


# ── IOC enrichment ───────────────────────────────────────────────────────────


async def _run_ioc_enrich_pending() -> dict[str, Any]:
    import redis as redis_lib
    from cti_api.services import ioc_providers
    from cti_api.services.ioc_enrichment import build_specs, enrich_pending
    from cti_core.db.engine import async_session
    from cti_core.runtime_secrets.overlay import effective_settings
    from cti_scraper.ratelimit import TokenBucket

    settings = effective_settings()
    bucket = TokenBucket(redis_lib.Redis.from_url(settings.redis.url))

    def allow(provider: str, rate: str) -> bool:
        return bucket.acquire(f"ioc-enrich:{provider}", rate)

    async with ioc_providers.make_client() as http:
        specs = build_specs(settings, http)
        if not specs:  # tidak ada kunci provider yang terisi: tidak ada yang dikerjakan
            return {}
        async with async_session() as session:
            return await enrich_pending(session, specs=specs, allow=allow)


@app.task(bind=True, name="ioc.enrich_pending", queue=QUEUE_MAINTENANCE)
def ioc_enrich_pending(self: Any) -> dict[str, object]:
    """Reputasi IOC dari provider luar (ROADMAP #4). Tanpa kunci terisi = no-op. Gagal sekali tidak
    di-retry: tick berikutnya (15 menit) memilih IOC yang sama lagi."""
    return _run_async(_run_ioc_enrich_pending())


# ── Weekly recap ─────────────────────────────────────────────────────────────
# Recap harian tidak lagi dijadwalkan (#21): task `recap.generate_daily` dibuang bersama entri
# beat-nya, tinggal pemicu tangan lewat `POST /api/recap/generate?kind=daily`.


async def _run_generate_weekly_recap() -> dict[str, Any]:
    from cti_api.services.recap import generate_weekly_recap
    from cti_core.db.engine import async_session

    async with async_session() as session:
        # `week_start=None`: pekan terakhir yang SUDAH selesai di UTC. Senin 00:15 UTC itu pekan
        # yang berakhir kemarin; run yang telat tetap dapat pekan yang sama.
        return await generate_weekly_recap(session, week_start=None, force=False)


@app.task(bind=True, name="recap.generate_weekly", queue=QUEUE_MAINTENANCE)
def generate_weekly_recap(self: Any) -> dict[str, object]:
    doc = _run_async(_run_generate_weekly_recap())
    return {"week_start": doc.get("date"), "cached": doc.get("cached")}


# ── Newsletter bulanan ───────────────────────────────────────────────────────


async def _run_prepare_newsletter_monthly() -> dict[str, Any]:
    from cti_api.services.newsletter_schedule import prepare_monthly
    from cti_core.db.engine import async_session

    # `async_session()` commit saat blok sukses (servisnya sendiri tidak commit) dan rollback
    # kalau exception. Gateway LLM yang mati BUKAN exception di sini: ranking tetap tersimpan dan
    # ringkasannya diulang hari kerja berikutnya (`summary_meta.error`). Yang tetap naik dan
    # di-rollback adalah kesalahan lain (DB dan sejenisnya), jadi tidak ada saran setengah jadi.
    async with async_session() as session:
        return await prepare_monthly(session, datetime.datetime.now(datetime.UTC))


@app.task(bind=True, name="newsletter.prepare_monthly", queue=QUEUE_MAINTENANCE)
def prepare_newsletter_monthly(self: Any) -> dict[str, object]:
    """Tiap hari kerja 09:00 WIB. Hampir selalu kembali segera (`prepared: False`): hanya hari
    kerja pertama bulan itu, dan hari-hari kejar sesudahnya selama jendela 7 hari dan bulan
    sebelumnya belum punya saran, yang benar-benar menyiapkan saran + Executive Summary; dan
    kalau ringkasannya gagal, hari-hari kejar mengulang ringkasannya saja."""
    return _run_async(_run_prepare_newsletter_monthly())


# ── CVE enrichment (CISA KEV + Exploit-DB + EPSS) ───────────────────────────


async def _run_cve_enrichment() -> dict[str, Any]:
    from cti_api.services.cve_lookup import (
        run_cisa_kev_lookup,
        run_epss_lookup,
        run_exploit_db_bulk_lookup,
    )
    from cti_core.db.engine import async_session

    # Satu session (= transaksi) per langkah: dulu satu session untuk ketiganya, jadi hasil KEV
    # baru ter-commit sesudah Exploit-DB dan EPSS selesai (> 1 jam), dan gagal satu langkah
    # (session rusak) ikut menggagalkan langkah berikutnya.
    steps = (
        ("cisa_kev", run_cisa_kev_lookup),
        ("exploit_db", run_exploit_db_bulk_lookup),
        ("epss", run_epss_lookup),
    )
    results: dict[str, Any] = {}
    for name, run in steps:
        try:
            async with async_session() as session:
                results[name] = await run(session)
        except Exception as e:
            log.warning(f"cve_enrichment_{name}_failed", error=str(e))
    return results


_SWEEP_LOCK_KEY = "cti:cve:enrichment_sweep:lock"
_SWEEP_LOCK_TTL_MS = 3 * 60 * 60 * 1000
"""Sama dengan jadwal (tiap 3 jam): lock yang tertinggal karena worker mati habis sendiri."""


def _sweep_lock() -> Any:
    import redis
    from cti_core.config import get_settings

    from cti_worker.beat_lock import BeatLock

    client = redis.Redis.from_url(get_settings().redis.url)
    return BeatLock(client, ttl_ms=_SWEEP_LOCK_TTL_MS, key=_SWEEP_LOCK_KEY)


@app.task(bind=True, name="cve.enrichment_sweep", queue=QUEUE_MAINTENANCE)
def cve_enrichment_sweep(self: Any) -> dict[str, object]:
    """Satu sweep sekaligus: prod 2026-11-06 dua sweep (sisa antrean `maintenance` sesudah
    deploy) jalan bersamaan dan saling menunggu lock baris `cve_tracker`."""
    lock = _sweep_lock()
    if not lock.acquire():
        log.info("cve_enrichment_skipped_running")
        return {"status": "skipped"}
    try:
        return _run_async(_run_cve_enrichment())
    finally:
        lock.release()


# ── Executive brief harian ───────────────────────────────────────────────────

_BRIEF_LOCK_TTL_MS = 15 * 60 * 1000
"""Jauh di atas satu build dashboard + `LLM__TIMEOUT_S` x (1 + `LLM__MAX_RETRIES`); lock yang
tertinggal karena worker mati habis sendiri sebelum tick berikutnya (>= 45 menit lagi)."""


def _brief_lock(brief_date: datetime.date) -> Any:
    import redis
    from cti_core.config import get_settings

    from cti_worker.beat_lock import BeatLock

    client = redis.Redis.from_url(get_settings().redis.url)
    return BeatLock(client, ttl_ms=_BRIEF_LOCK_TTL_MS, key=f"exec_brief:{brief_date.isoformat()}")


async def _brief_present(brief_date: datetime.date) -> bool:
    from cti_core.db.engine import async_session
    from cti_core.db.repositories.exec_brief import AsyncExecBriefRepo

    async with async_session() as session:
        return await AsyncExecBriefRepo(session).get(brief_date) is not None


async def _run_generate_scheduled_brief() -> str:
    from cti_api.services.exec_brief import generate_scheduled_brief
    from cti_core.db.engine import async_session

    async with async_session() as session:
        return await generate_scheduled_brief(session, datetime.datetime.now(datetime.UTC))


@app.task(bind=True, name="exec.brief_daily", queue=QUEUE_MAINTENANCE)
def exec_brief_daily(self: Any) -> dict[str, object]:
    """Brief eksekutif bersama, dicoba tiap jam lokal 06:00-18:00 (tick 06:00 hanyalah yang
    pertama; tick berikutnya = catch-up bila LLM mati). Satu percobaan per jam, tanpa retry
    Celery, tanpa baris gagal/job: `enrich_jobs` (kunci URL artikel, CHECK `classify`/`ttp`) dan
    breaker (hanya dihitung dari `classify`/`ttp`) sengaja tidak dipakai, supaya brief tidak
    mengubah dispatch artikel. Jaga panggilan ganda ada tiga lapis: (a) lock Redis
    `exec_brief:{tanggal}` menyerialkan tick yang tumpang tindih atau `celery call` manual;
    (b) baca ulang baris di bawah lock membuat pemegang kedua no-op; (c) `ON CONFLICT DO
    NOTHING` melindungi brief manual. `expires` 55 menit < `visibility_timeout` Redis 60 menit:
    pesan yang dikirim ulang sesudah worker mati sudah kedaluwarsa dan dibuang."""
    from cti_api.services.exec_brief import BriefGenerationError, brief_today
    from cti_core.config import get_settings

    brief_date = brief_today()
    # Cek murah dulu: sebagian besar tick hari itu berhenti di sini, tanpa lock dan tanpa LLM.
    if _run_async(_brief_present(brief_date)):
        return {"status": "present"}
    lock = _brief_lock(brief_date)
    if not lock.acquire():
        log.info("exec_brief_daily_skipped_running", brief_date=brief_date.isoformat())
        return {"status": "skipped_running"}
    try:
        return {"status": _run_async(_run_generate_scheduled_brief())}
    except BriefGenerationError as exc:
        log.warning(
            "exec_brief_daily_failed",
            brief_date=brief_date.isoformat(),
            error_type=exc.error_type,
            local_hour=(
                datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=get_settings().worker.report_utc_offset_hours)
            ).hour,
        )
        return {"status": "failed"}
    finally:
        lock.release()
