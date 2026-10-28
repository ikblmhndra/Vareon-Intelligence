"""App Celery -- SATU app, dua "image" (scrape vs enrich) dibedain lewat
`-Q` (queue mana yang di-consume) + extra `nlp` (`cti-enrich[nlp]`) yang
ke-install atau nggak, BUKAN dua app/codebase terpisah. Modul task
(`tasks/scrape.py`, `tasks/enrich.py`) di-import di sini SELALU biar Celery
bisa route ke keduanya dari app mana pun yang nyambung ke broker yang
sama -- tapi import berat (`cti_enrich`, spaCy/sumy) ada DI DALAM fungsi
task `enrich.article` (lazy, pola sama kayak sink di `cti_scraper.sinks`),
bukan di top-level modul ini. Itu yang bikin worker scrape-only (image
tanpa extra `nlp` ke-install) tetap bisa start dan liat task `enrich.article`
terdaftar (perlu buat routing yang bener), walau manggil beneran bakal
`ImportError` -- itu OK, `-Q` yang jamin worker itu emang gak pernah
di-assign task ini (lihat plan §4 image `worker-scrape` vs `worker-nlp`).
"""

from __future__ import annotations

from celery import Celery
from cti_core.config import get_settings

settings = get_settings()

app = Celery("cti_worker", broker=settings.redis.url)
app.conf.task_ignore_result = True
app.conf.task_routes = {}  # queue ditentuin per-dispatch (beat options / apply_async), bukan statis
app.conf.timezone = "UTC"
app.conf.worker_prefetch_multiplier = 1
app.conf.task_acks_late = True
"""ACK setelah task SELESAI, bukan pas diterima -- worker mati di tengah
`scrape.run`/`enrich.article` (OOM, restart deploy) bikin broker Redis
nge-redeliver task itu ke worker lain, bukan diam-diam hilang. Trade-off
sadar: task yang crash-loop (bug, bukan worker mati) bakal ke-retry sampai
`max_retries` alih-alih ilang -- diterima, karena silent data loss lebih
mahal daripada retry ekstra buat scraper/enrich yang idempoten."""
app.conf.broker_transport_options = {"visibility_timeout": 3600}
"""Redis-as-broker (bukan RabbitMQ) gak punya native ack -- "unacked" task
di-redeliver otomatis kalau lewat visibility_timeout ini walau worker-nya
masih hidup dan lagi ngerjain (task lambat = redelivery + eksekusi dobel).
3600s jauh di atas task terlama yang keukur LIVE (`enrich.article` ~10-13s
per artikel, `scrape.run` ~1-2s) -- longgar sengaja, breaking-nya baru
kerasa kalau task pernah nyangkut lebih dari sejam."""
"""Default Celery (4) nyabut N task sekaligus per worker child -- buat
scraper (`items_found` bisa lama, network-bound) itu bikin satu worker
lambat nge-block N-1 task lain nunggu giliran. 1 = ambil task berikutnya
cuma setelah yang sekarang kelar."""

app.conf.beat_scheduler = "cti_worker.scheduler:CtiScheduler"
"""QA BUG-D2/D7/D8 -- `PersistentScheduler` + heartbeat Redis + tanpa catch-up
basi pas start. Lihat docstring `cti_worker.scheduler`."""
app.conf.beat_max_interval = 60
"""Default Celery 300 dtk: kalau gak ada entri due, loop beat bisa tidur 5
menit -- heartbeat (ditulis per tick) jadi kasar. 60 = heartbeat paling basi
~1 menit pas beat sehat; ambang `beat_heartbeat_stale_s` (300) = 5 tick
kelewat. Biayanya cuma satu iterasi heap per menit."""

from celery.signals import (  # noqa: E402
    after_setup_logger,
    after_setup_task_logger,
    worker_process_init,
    worker_ready,
)


@worker_ready.connect
def _start_beat_watchdog(**_kwargs: object) -> None:
    """Proses INDUK worker (bukan child prefork) -- lihat `cti_worker.beat_watchdog`."""
    from cti_worker import beat_watchdog

    beat_watchdog.start()


@after_setup_logger.connect
@after_setup_task_logger.connect
def _quiet_http_loggers(**_kwargs: object) -> None:
    """Worker tidak memanggil `configure_logging`, jadi tanpa ini httpx mencatat URL penuh di INFO
    dan token bot Telegram (path URL-nya) masuk log container tiap alert terkirim."""
    from cti_core.logging import quiet_http_loggers

    quiet_http_loggers()


@worker_process_init.connect
def _fresh_db_pool_per_child(**_kwargs: object) -> None:
    """Tiap proses anak prefork mulai dgn pool DB KOSONG -- jangan warisi
    koneksi induk (lihat `cti_core.db.engine.discard_inherited_connections`)."""
    from cti_core.db.engine import discard_inherited_connections

    discard_inherited_connections()


from cti_worker.beat import build_beat_schedule  # noqa: E402
from cti_worker.tasks import (  # noqa: E402,F401  -- registrasi task, harus setelah `app` ada
    confidence,
    cve_mirror,
    enrich,
    indicator,
    llm_maintenance,
    periodic,
    relevance,
    reports,
    scrape,
    story,
)

app.conf.beat_schedule = build_beat_schedule()
"""Dibangun sekali pas modul ini di-import (worker ATAU beat, dua-duanya
connect app yang sama) -- `discover()` (registry) di-cache per-proses,
murah dipanggil ulang. Beat restart = jadwal ke-generate ulang otomatis,
gak ada file terpisah yang bisa basi."""
