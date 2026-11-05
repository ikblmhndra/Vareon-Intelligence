"""Klien Celery RINGAN buat producer yang gak boleh depends ke `apps/worker`
(mis. `cti_scraper.sinks` -- lihat `_article_sink`, Fase 6). Cuma bawa
koneksi broker, TIDAK import task apa pun -- `send_task(name, ...)` kirim
lewat NAMA task, cocok lewat routing key/queue yang sama, task Python-nya
gak perlu ke-import di sisi pengirim.

Ini yang bikin arah dependency tetap bener: `packages/cti-scraper` gak
boleh depends ke `apps/worker` (apps depends ke packages, bukan sebaliknya)
-- broker Redis yang jadi kontrak di antara keduanya, bukan import Python."""

from __future__ import annotations

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


def send_enrich_llm(job_id: int, decision: str | None = None) -> None:
    """Kirim satu job `enrich_jobs` ke task `enrich.llm` (P7g; dispatcher dan aksi analis).
    `decision` (`accept`/`reject`, keputusan analis) hanya ikut dikirim bila ada."""
    kwargs: dict[str, object] = {"job_id": job_id}
    if decision is not None:
        kwargs["decision"] = decision
    get_celery_client().send_task("enrich.llm", kwargs=kwargs, queue="enrich")


def send_recompute_source(source_name: str) -> None:
    """Minta worker menghitung ulang `confidence_score` artikel satu sumber (grade sumber baru
    dibuat atau diubah, rilis 0.8.6). Antrian `maintenance`."""
    get_celery_client().send_task(
        "confidence.recompute_source", kwargs={"source_name": source_name}, queue="maintenance"
    )


def send_recompute_all() -> None:
    """Minta worker menghitung ulang `confidence_score` SEMUA artikel (pertama kali grade bawaan
    dibuat saat API start, rilis 0.8.6). Satu pesan, antrian `maintenance`."""
    get_celery_client().send_task("confidence.recompute_all", queue="maintenance")


def send_reconcile_validity() -> None:
    """Minta worker mengisi/menyinkronkan `indicators.valid_until` dari TTL settings (API start
    dengan sidik jari TTL berubah, P7a). Satu pesan, antrian `maintenance`."""
    get_celery_client().send_task("indicator.reconcile_validity", queue="maintenance")
