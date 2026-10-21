"""Task `scrape.run` -- eksekusi SATU scraper. Beat (`cti_worker.beat`)
manggil ini terjadwal per scraper (`args=(scraper_id,)`, `trigger` default
"beat", `queue=` dinamis lewat `cti_worker.queues.queue_for`); control
plane (Fase 9, `POST /api/scraper/{id}/trigger`) manggil task YANG SAMA
lewat `.delay(scraper_id, trigger="manual")` -- `Runner`/`ScraperRun.
trigger` yang bedain asalnya, bukan task terpisah.

Retry di LEVEL TASK (whole run), bukan per-request -- `ScraperHttpClient`
(Fase 3) sengaja gak retry sendiri per `httpx.get()`, dan `Runner`
(`runner.py`) sengaja NANGKEP `TransientFetchError`/`RateLimited` jadi
`RunResult.status`, bukan biarin exception nembus (baca docstring
`Runner._run_body`: "runner ini SENGAJA gak retry sendiri; caller yang
urus"). Task ini itu "caller"-nya: cek `result.status`, lalu `self.retry()`
dengan jeda dari `retry_countdown()` -- `ParseError` (situs berubah) TIDAK
PERNAH masuk sini, `status="parse_error"` dibiarin apa adanya (retry gak
bakal ngubah hasil situs yang emang berubah).

QA BUG-D6 (staging 2026-10-01): dulu `autoretry_for` + `retry_backoff=True`
-> jeda 1/2/4/8 dtk (faktor 1, full jitter), jadi `monitor_x` nyoba 4x dalam
~10 dtk tiap slot, semuanya mentok budget rate-limit domain yang SAMA (jendela
60 dtk), dan tiap percobaan tercatat sebagai run `trigger=beat` terpisah --
riwayat 132 run vs 33 slot cron. Sekarang: jeda minimal `_RETRY_BASE_S`
dobel tiap percobaan (dan gak kurang dari `RunResult.retry_after`), dan run
hasil retry dicatat `trigger="<asal>_retry"` (`beat_retry`/`manual_retry`)
biar riwayat bisa bedain slot jadwal vs percobaan ulang. Retry tetap numpang
`expires` tick aslinya (Celery bawa `expires` lintas retry) -- percobaan
yang lewat satu interval jadwal dibuang, gak numpuk ke slot berikutnya.

Task `scraper.purge_expired_items`/`scraper.purge_expired_seen` (Fase 9,
`maintenance` queue) numpang file ini juga -- sama domain (scraper), sync
native (bukan `_run_async()` kayak `tasks/periodic.py`, soalnya manggil
repo SYNC langsung, gak ada layer `cti_api.services` async yang dibungkus)."""

from __future__ import annotations

from typing import Any

import structlog

from cti_worker.celery_app import app

log = structlog.get_logger()


_RETRYABLE_STATUSES = frozenset({"fetch_error", "rate_limited"})
_RETRY_BASE_S = 60
_RETRY_MAX_S = 600
_RETRY_SUFFIX = "_retry"


class _RetryableRunError(Exception):
    """Exception yang dibawa `self.retry(exc=...)` -- bukan exception yang
    Runner/scraper lempar, murni penanda run yang gagal transien. Kalau
    `max_retries` habis, ini yang jadi kegagalan akhir task."""


def retry_countdown(attempt: int, retry_after: float | None = None) -> int:
    """Jeda sebelum percobaan ke-`attempt + 1`: 60, 120, 240, ... (maks 600)
    detik, dan gak pernah lebih pendek dari `retry_after` (mis. sisa jendela
    rate-limit). Deterministik -- `spread()` udah nyebar jadwal antar scraper."""
    backoff = min(_RETRY_MAX_S, _RETRY_BASE_S * 2**attempt)
    return int(max(backoff, retry_after or 0))


def retry_trigger(trigger: str) -> str:
    """`beat` -> `beat_retry`, `manual` -> `manual_retry`; idempoten.
    Muat di `ScraperRun.trigger` (String(20))."""
    return trigger if trigger.endswith(_RETRY_SUFFIX) else f"{trigger}{_RETRY_SUFFIX}"


@app.task(bind=True, name="scrape.run", max_retries=3)
def run_scraper(self: Any, scraper_id: str, trigger: str = "beat") -> dict[str, object]:
    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_scraper.ratelimit import TokenBucket
    from cti_scraper.registry import discover
    from cti_scraper.runner import Runner

    registry = discover()
    scraper_cls = registry.get(scraper_id)
    if scraper_cls is None:
        # ID gak ketemu (typo di beat schedule, atau scraper udah dihapus
        # tapi jadwal lama masih ke-generate) -- fail keras, JANGAN retry,
        # retry gak bakal bikin scraper itu muncul.
        raise ValueError(f"scraper '{scraper_id}' gak ketemu di registry")

    settings = get_settings()
    import redis as redis_lib

    bucket = TokenBucket(redis_lib.Redis.from_url(settings.redis.url))

    with sync_session() as session:
        result = Runner(
            scraper_cls,
            session=session,
            bucket=bucket,
            dry_run=False,
            celery_task_id=self.request.id,
            worker=self.request.hostname,
            attempt=(self.request.retries or 0) + 1,
        ).execute(trigger=trigger)

    if result.status in _RETRYABLE_STATUSES:
        attempt = self.request.retries or 0
        countdown = retry_countdown(attempt, result.retry_after)
        log.warning(
            "scrape_task_retrying",
            scraper_id=scraper_id,
            status=result.status,
            attempt=attempt,
            countdown_s=countdown,
        )
        raise self.retry(
            args=(scraper_id,),
            kwargs={"trigger": retry_trigger(trigger)},
            countdown=countdown,
            exc=_RetryableRunError(f"{scraper_id}: {result.status}"),
        )

    return {
        "scraper_id": scraper_id,
        "status": result.status,
        "items_found": result.items_found,
        "items_new": result.items_new,
    }


@app.task(bind=True, name="scraper.purge_expired_items", queue="maintenance")
def purge_expired_items(self: Any) -> dict[str, object]:
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.scraper import ScraperItemRepo

    with sync_session() as session:
        deleted = ScraperItemRepo(session).purge_expired()
    log.info("scraper_items_purged", deleted=deleted)
    return {"deleted": deleted}


@app.task(bind=True, name="scraper.purge_expired_seen", queue="maintenance")
def purge_expired_seen(self: Any) -> dict[str, object]:
    """`scraper_seen.expire_at` udah ada dari Fase 2, tapi task ini gak
    pernah ditulis sampai Fase 9 -- baris in-flight (1 hari) dan committed
    (`dedup_ttl_days`, default 180) numpuk gak abis-abis dari hari pertama
    deploy sampai sekarang."""
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.scraper_seen import ScraperSeenRepo

    with sync_session() as session:
        deleted = ScraperSeenRepo(session).purge_expired()
    log.info("scraper_seen_purged", deleted=deleted)
    return {"deleted": deleted}


@app.task(bind=True, name="scraper.reap_stale_runs", queue="maintenance")
def reap_stale_runs(self: Any) -> dict[str, object]:
    """Tutup run yang yatim: worker mati atau di-redeploy saat run jalan meninggalkan baris
    `running` selamanya (dev: 8 baris, tertua 3 minggu), padahal `/api/scraper` menampilkannya
    sebagai status terakhir dan health menilai dari situ. Jadi `timeout` setelah
    `scraper_run_stale_hours` (di atas visibility timeout Celery 1 jam)."""
    import datetime

    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.scraper import ScraperRunRepo

    stale_after = datetime.timedelta(hours=get_settings().worker.scraper_run_stale_hours)
    with sync_session() as session:
        reaped = ScraperRunRepo(session).reap_stale_running(stale_after)
    if reaped:
        log.warning("scraper_runs_reaped", reaped=reaped, stale_after=str(stale_after))
    return {"reaped": reaped}


@app.task(bind=True, name="scraper.purge_old_runs", queue="maintenance")
def purge_old_runs(self: Any) -> dict[str, object]:
    """`scraper_runs` tumbuh ~1-2 ribu baris per hari (satu per tick per scraper) dan tidak pernah
    dibersihkan; `/api/scraper/health` dan digest memindainya. Retensi minimal sama dengan
    `scraper_items` karena `scraper_items.run_id` cascade."""
    import datetime

    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.scraper import ScraperRunRepo

    worker = get_settings().worker
    days = max(worker.scraper_run_retention_days, worker.scraper_item_retention_days)
    with sync_session() as session:
        deleted = ScraperRunRepo(session).purge_older_than(datetime.timedelta(days=days))
    log.info("scraper_runs_purged", deleted=deleted, retention_days=days)
    return {"deleted": deleted}


def _digest_due(problems: list[Any], repeat_s: int, client: Any = None) -> bool:
    """Daftar masalah yang SAMA (id + status) tidak dikirim ulang dalam `repeat_s`: sebelumnya
    digest 30 menit mengulang pesan yang identik selama masalahnya ada. Daftar yang BERUBAH
    (scraper baru bermasalah atau pulih) langsung terkirim. Redis mati = kirim saja (fail-open)."""
    import hashlib

    signature = hashlib.sha1(
        "|".join(sorted(f"{e.scraper_id}:{e.status}" for e in problems)).encode()
    ).hexdigest()[:16]
    try:
        if client is None:
            import redis as redis_lib
            from cti_core.config import get_settings

            client = redis_lib.Redis.from_url(get_settings().redis.url)
        return bool(client.set(f"cti:scraper:health_digest:{signature}", "1", nx=True, ex=repeat_s))
    except Exception as e:
        log.warning("scraper_health_digest_dedupe_failed", error=str(e)[:200])
        return True


@app.task(bind=True, name="scraper.health_digest", queue="notify")
def scraper_health_digest(self: Any) -> dict[str, object]:
    """SATU pesan Telegram konsolidasi (topic `scraper_health`, perlu
    ditambahin ke `TELEGRAM__THREAD_IDS` operator) tiap sweep -- gantiin
    kelas masalah yang sama kayak 14 fungsi `send_alert_*` lama
    (`cti_alerts.telegram`'s docstring): satu alert per scraper bermasalah
    bakal jadi puluhan pesan kalau lagi ada insiden luas, di sini digabung
    jadi satu. GAK ngirim apa-apa kalau semua `ok`/`disabled` -- diam itu
    sinyal "sehat", bukan di-spam tiap tick."""
    import html

    from cti_alerts.telegram import send_alert
    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.scraper import ScraperConfigRepo, ScraperRunRepo
    from cti_scraper.health import summarize_fleet_health
    from cti_scraper.registry import discover

    registry = discover()
    with sync_session() as session:
        configs = ScraperConfigRepo(session).get_all()
        run_repo = ScraperRunRepo(session)
        recent_runs = run_repo.list_recent_by_scraper_bulk(limit=3)
        last_success = run_repo.last_success_by_scraper()

    entries = summarize_fleet_health(registry, configs, recent_runs, last_success=last_success)
    problems = [e for e in entries if e.status not in ("ok", "disabled")]
    if not problems:
        log.info("scraper_health_digest_clean", total=len(entries))
        return {"problems": 0, "total": len(entries)}

    settings = get_settings()
    if not _digest_due(problems, settings.worker.scraper_health_repeat_min * 60):
        log.info("scraper_health_digest_suppressed", problems=len(problems), total=len(entries))
        return {"problems": len(problems), "total": len(entries), "sent": False}

    by_status: dict[str, list[str]] = {}
    for e in problems:
        line = f"{e.scraper_id} ({e.source})"
        if e.reason:
            line += f": {html.escape(e.reason)}"
        by_status.setdefault(e.status, []).append(line)

    lines = [f"<b>Scraper Health</b> -- {len(problems)}/{len(entries)} bermasalah"]
    for status in sorted(by_status):
        lines.append(f"\n<b>{status}</b> ({len(by_status[status])}):")
        lines.extend(f"  • {s}" for s in sorted(by_status[status]))

    send_alert("scraper_health", "\n".join(lines))
    log.info("scraper_health_digest_sent", problems=len(problems), total=len(entries))
    return {"problems": len(problems), "total": len(entries), "sent": True}
