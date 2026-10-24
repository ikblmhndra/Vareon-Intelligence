"""Klien Celery RINGAN buat producer yang gak boleh depends ke `apps/worker`
(mis. `cti_scraper.sinks` -- lihat `_article_sink`, Fase 6). Cuma bawa
koneksi broker, TIDAK import task apa pun -- `send_task(name, ...)` kirim
lewat NAMA task, cocok lewat routing key/queue yang sama, task Python-nya
gak perlu ke-import di sisi pengirim.

Ini yang bikin arah dependency tetap bener: `packages/cti-scraper` gak
boleh depends ke `apps/worker` (apps depends ke packages, bukan sebaliknya)
-- broker Redis yang jadi kontrak di antara keduanya, bukan import Python."""

from __future__ import annotations

import datetime
from functools import lru_cache

from celery import Celery

from cti_core.config import get_settings


@lru_cache(maxsize=1)
def get_celery_client() -> Celery:
    """Satu instance per proses -- Celery app TANPA task terdaftar, cuma
    dipakai `.send_task(name, kwargs=...)`. Broker = Redis yang sama
    dipakai worker (`RedisSettings.url`); result backend sengaja gak
    di-set -- task di sini fire-and-forget (efek sampingnya nulis
    Postgres, bukan return value yang perlu dikumpulin pengirim)."""
    settings = get_settings()
    app = Celery("cti_producer", broker=settings.redis.url)
    app.conf.task_ignore_result = True
    return app


def send_enrich_task(
    *,
    title: str,
    url: str,
    posted_on: datetime.date | None,
    source: str,
    scraper_id: str | None,
    replay: bool = False,
    alert: bool | None = None,
) -> None:
    """Kirim ulang satu artikel ke `enrich.article` (replay artikel yang gagal di-enrich: tool
    `replay_failed_enrichment` dan endpoint replay di API). Argumennya sama dengan yang dikirim
    `cti_scraper.sinks._article_sink`; `replay=True` membuat pipeline TIDAK mengirim alert Telegram
    (beritanya sudah basi). `replay` hanya ikut dikirim bila True: pesan biasa tidak berubah.
    `alert` (bukan None) menimpa bawaan `not replay`; None = tidak dikirim."""
    kwargs: dict[str, object] = {
        "title": title,
        "url": url,
        "posted_on": posted_on.isoformat() if posted_on else None,
        "source": source,
        "scraper_id": scraper_id,
    }
    if replay:
        kwargs["replay"] = True
    if alert is not None:
        kwargs["alert"] = alert
    get_celery_client().send_task("enrich.article", kwargs=kwargs, queue="enrich")
