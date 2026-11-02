"""Dispatcher job LLM `enrich.llm_dispatch` (P7g, spec 4.5) dan alert enrichment-nya.

Tiap menit (beat, antrian `maintenance`): status circuit breaker dihitung dari `llm_calls`
terbaru (`cti_core.llm.breaker`), lalu job `enrich_jobs` yang jatuh tempo dikirim ke `enrich.llm`.
Tertutup: sampai `BATCH`, dibatasi sisa ruang antrian `enrich` (aturan backpressure yang sama);
setengah terbuka: satu canary; terbuka: tidak ada, dan alert "gateway LLM mati". Menggantikan
replay otomatis tiap 10 menit: tidak ada lagi artikel `[enrichment_failed]` yang perlu di-replay,
semuanya sudah tersimpan sebagai job.

Urutan pola P1: klaim (geser `next_attempt_at` sebesar `LEASE`) + COMMIT dulu, baru kirim. Crash
di antaranya tidak bisa membuat kirim ulang tanpa henti; gagal kirim sesudah commit cukup dicatat
(lease habis, dispatcher mengirimnya lagi). Kiriman ganda aman: `run_job` idempoten.

Alert (`alert_llm_down`, `alert_job_failed`) menggantikan `_alert_enrichment_failure` lama:
best-effort, dedupe lintas proses lewat Redis `SET NX EX` (satu kunci per jenis alert), jendela
`worker.enrich_failure_alert_cooldown_min`. Kegagalan massal = ratusan job, cukup SATU pesan."""

from __future__ import annotations

import datetime
import html

import structlog

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_MAINTENANCE

log = structlog.get_logger()

_DOWN_ALERT_KEY = "cti:enrich:llm_down_alerted"
_FAILED_ALERT_KEY = "cti:enrich:job_failed_alerted"


def _alert_once(key: str, text: str) -> None:
    """Kirim `text` ke Telegram kalau kunci `key` belum ada di Redis (jendela cooldown).
    BEST-EFFORT: tidak pernah melempar, kegagalan aslinya sudah tercatat di tempat lain."""
    try:
        import redis
        from cti_alerts.telegram import send_alert
        from cti_core.config import get_settings

        settings = get_settings()
        client = redis.Redis.from_url(settings.redis.url)
        cooldown_s = settings.worker.enrich_failure_alert_cooldown_min * 60
        if not client.set(key, "1", nx=True, ex=cooldown_s):
            return
        send_alert("scraper_health", text)
    except Exception as alert_error:
        log.error("enrich_alert_failed", key=key, error=str(alert_error)[:200])


def alert_llm_down(waiting: int) -> None:
    """Breaker terbuka: gateway LLM gagal beruntun. Artikelnya aman (tersimpan sebagai job) dan
    akan diproses sendiri begitu gateway pulih; pesan ini supaya penyebabnya diperiksa."""
    _alert_once(
        _DOWN_ALERT_KEY,
        "<b>Gateway LLM mati</b> -- enrichment ditahan circuit breaker.\n"
        f"Menunggu: {waiting} artikel. Tersimpan sebagai job dan diproses otomatis begitu "
        "gateway pulih; cek gateway/model/kuota.",
    )


def alert_job_failed(title: str, error: str) -> None:
    """Satu job menjadi `failed` (bug, JSON rusak berulang, retry DB habis): menunggu analis di
    antrean enrichment Newsroom (coba lagi / terima / tolak)."""
    _alert_once(
        _FAILED_ALERT_KEY,
        "<b>Job enrichment GAGAL</b> -- menunggu keputusan analis.\n"
        f"{html.escape(title)}\n<code>{html.escape(error)}</code>\n"
        "Cek antrean enrichment di Newsroom (coba lagi / terima / tolak).",
    )


def dispatch(now: datetime.datetime) -> dict[str, int]:
    """Satu putaran dispatcher pada waktu `now` (dipisah dari task supaya bisa diuji dengan jam
    simulasi). Return `{"sent", "failed", "limit"}`."""
    from cti_core.celery_client import send_enrich_llm
    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.enrich_job import EnrichJobRepo
    from cti_core.db.repositories.llm_call import LlmCallRepo
    from cti_core.llm.breaker import (
        BREAKER_TASKS,
        LEASE,
        RECENT_CALLS,
        breaker_state,
        dispatch_limit,
    )
    from cti_scraper.sinks import enrich_queue_depth

    waiting = 0
    with sync_session() as session:
        recent = LlmCallRepo(session).recent_for_tasks(BREAKER_TASKS, limit=RECENT_CALLS)
        breaker = breaker_state(recent, now)
        limit = dispatch_limit(
            breaker,
            queue_depth=enrich_queue_depth(),
            max_depth=get_settings().scraper.enrich_queue_max_depth,
        )
        repo = EnrichJobRepo(session)
        if breaker.state == "open":
            counts = repo.counts()
            waiting = counts.pending_classify + counts.pending_ttp
        job_ids = [j.id for j in repo.claim_due(now, limit=limit, lease=LEASE)] if limit else []
        session.commit()

    if waiting:
        # Tanpa job yang menunggu tidak ada canary yang bisa menutup breaker, jadi alert-nya
        # akan berulang tiap jendela walau gateway sudah pulih: dilewati.
        alert_llm_down(waiting)

    sent = failed = 0
    for job_id in job_ids:
        try:
            send_enrich_llm(job_id)
            sent += 1
        except Exception:
            failed += 1
            log.warning("llm_dispatch_send_failed", job_id=job_id, exc_info=True)
    log.info(
        "llm_dispatched",
        breaker=breaker.state,
        failures=breaker.failures,
        limit=limit,
        sent=sent,
        failed=failed,
        waiting=waiting,
    )
    return {"sent": sent, "failed": failed, "limit": limit}


@app.task(name="enrich.llm_dispatch", queue=QUEUE_MAINTENANCE)
def llm_dispatch() -> dict[str, int]:
    return dispatch(datetime.datetime.now(datetime.UTC))
