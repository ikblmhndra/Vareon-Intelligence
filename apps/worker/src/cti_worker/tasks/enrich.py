"""Task `enrich.article` -- gantiin tulis-langsung `_article_sink` (Fase 3).
`fetch()` scraper mana pun yang nge-`yield` `ArticleItem` sekarang mendarat
di sini via `send_task`, bukan `ArticleRepo.upsert()` langsung -- lihat
`cti_scraper.sinks._article_sink` (Fase 6), kontrak "tipe apa masuk situ"
gak berubah, cuma titik tulisnya pindah dari sink SINKRON ke task ASINKRON.

Import `cti_enrich` (spaCy/sumy) LAZY di dalam fungsi -- baca docstring
`cti_worker.celery_app` soal kenapa (worker scrape-only, image tanpa extra
`nlp`, tetep bisa start walau task ini gak pernah beneran dia jalanin).

Kebijakan kegagalan (Fase 10.A2, diubah P7g) -- SATU prinsip: artikel yang sudah lolos
dedup (`scraper_seen` udah di-commit pas `send_task`) TIDAK BOLEH hilang tanpa
jejak. Sejak P7g task ini TIDAK memanggil LLM (`run_pipeline` menyimpan artikel yang
relevansinya sudah diketahui, sisanya jadi job `classify` di `enrich_jobs`), jadi kegagalan
gateway LLM tidak pernah sampai ke sini; itu urusan job runner (`enrich.llm`). Tersisa:

1. **Transien** (koneksi DB putus, jaringan `httpx`): retry sampai 6x, backoff eksponensial
   30s -> 10 mnt (+jitter), total ~30 menit.
2. **Gagal final** (retry habis, atau error lain/bug): `on_failure` menulis job `classify`
   ber-`state='failed'` dengan `input_text=NULL` (bagian depan pipeline diulang saat job
   dijalankan lagi) dan `last_error` -> muncul di antrean enrichment Newsroom, analis bisa
   retry/terima/tolak. Kalau artikelnya SUDAH tersimpan (gagal SESUDAH `persist`, mis. Telegram
   down) gak ada yang dicatat -- gak ada yang hilang."""

from __future__ import annotations

import datetime
import random
from typing import Any, Literal, cast

import httpx
import sqlalchemy.exc
import structlog
from celery import Task

from cti_worker.celery_app import app

log = structlog.get_logger()

# Error LLM (openai, `EmptyLLMResponse`, JSON rusak) tidak ada lagi di sini: task ini tidak
# memanggil LLM sejak P7g. Kegagalan gateway ditangani job runner tanpa retry Celery.
_TRANSIENT_ERRORS = (
    httpx.TransportError,
    sqlalchemy.exc.OperationalError,  # koneksi DB putus / server restart
    sqlalchemy.exc.InterfaceError,
)
_MAX_RETRIES_TRANSIENT = 6


def _backoff_s(retries: int) -> float:
    """30s, 60s, 120s, ... maks 600s, +0-25% jitter (biar ratusan task yang
    gagal barengan gak nyerbu gateway yang baru pulih di detik yang sama)."""
    return float(min(600, 30 * 2**retries)) * (1 + random.random() * 0.25)


def _relevance_for(scraper_id: str | None) -> tuple[str | None, str, str, str]:
    """`(content_kind, default_relevance, tlp, pap)` dari `ScraperMeta`; `(None, "classify",
    "clear", "clear")` untuk `scraper_id` kosong atau sudah tidak terdaftar (mis. replay baris
    lama) -- classify jalan seperti biasa. Lookup di sini karena `cti_enrich` tidak boleh
    mengimpor `cti_scraper`."""
    if not scraper_id:
        return None, "classify", "clear", "clear"
    from cti_scraper import registry

    try:
        meta = registry.get(scraper_id).meta
    except KeyError:
        return None, "classify", "clear", "clear"
    return meta.content_kind, meta.default_relevance, meta.tlp, meta.pap


def _scrub_secrets(text: str) -> str:
    """Buang secret yang DIKONFIGURASI dari teks error sebelum masuk DB/UI: provider kadang
    ngecho (sebagian) API key di pesan errornya. Implementasinya satu, dipakai juga job runner
    `cti_enrich.jobs` (`cti_core.runtime_secrets.overlay.scrub_secrets`, tidak pernah raise)."""
    from cti_core.runtime_secrets.overlay import scrub_secrets

    return scrub_secrets(text)


_FAILURE_ALERT_KEY = "cti:enrich:failed_alerted"


def _alert_enrichment_failure(error_type: str, message: str, waiting: int) -> None:
    """Satu alert Telegram per jendela cooldown: kegagalan massal (model salah, kuota habis,
    gateway mati) = ratusan task, dan sebelum ini tidak ada sinyal selain laporan harian 23:55.
    Dedupe lintas proses worker-nlp lewat Redis (pola `beat_watchdog`). BEST-EFFORT: tidak
    pernah menutupi kegagalan aslinya."""
    try:
        import html

        import redis
        from cti_alerts.telegram import send_alert
        from cti_core.config import get_settings

        settings = get_settings()
        client = redis.Redis.from_url(settings.redis.url)
        cooldown_s = settings.worker.enrich_failure_alert_cooldown_min * 60
        if not client.set(_FAILURE_ALERT_KEY, "1", nx=True, ex=cooldown_s):
            return
        send_alert(
            "scraper_health",
            "<b>Enrichment artikel GAGAL</b> -- artikelnya belum diproses.\n"
            f"<code>{html.escape(error_type)}</code>: {html.escape(message)}\n"
            f"Menunggu replay: {waiting} artikel. Perbaiki penyebabnya dulu, lalu replay dari "
            "Newsroom > Failed enrichment.",
        )
    except Exception as alert_error:
        log.error("enrich_failure_alert_failed", error=str(alert_error)[:200])


def _record_failed_job(kwargs: dict[str, Any], exc: BaseException, error_type: str) -> None:
    """Catat artikel yang gagal di-enrich sebagai job `classify` `failed` (P7g, menggantikan
    baris `[enrichment_failed]` di `rejected_articles`). `input_text=NULL`: job runner menjalankan
    `prepare` dulu. `context` membawa marking/relevansi bawaan sumber karena `cti_enrich` tidak
    bisa mencarinya sendiri (`_relevance_for`). BEST-EFFORT: gagal nulis catatan ini gak boleh
    nutupi kegagalan aslinya (cuma di-log)."""
    url = kwargs.get("url", "?")
    try:
        from cti_core.db.engine import sync_session
        from cti_core.db.models.article import Article
        from cti_core.db.repositories.enrich_job import EnrichJobRepo
        from cti_core.urlkit import url_hash
        from sqlalchemy import select

        with sync_session() as session:
            exists = session.scalar(select(Article.id).where(Article.url_hash == url_hash(url)))
            if exists is not None:
                # Gagal SESUDAH persist (mis. alert Telegram) -- artikelnya aman.
                log.error("enrich_failed_after_persist", url=url, error=str(exc)[:300])
                return
            posted = kwargs.get("posted_on")
            scraper_id = kwargs.get("scraper_id")
            content_kind, default_relevance, tlp, pap = _relevance_for(scraper_id)
            job = EnrichJobRepo(session).create(
                kind="classify",
                url=url,
                title=kwargs.get("title", ""),
                source=kwargs.get("source", ""),
                scraper_id=scraper_id,
                posted_on=datetime.date.fromisoformat(posted) if posted else None,
                input_text=None,
                context={
                    "content_kind": content_kind,
                    "default_relevance": default_relevance,
                    "tlp": tlp,
                    "pap": pap,
                },
                state="failed",
                # Scrub SEBELUM dipotong (repo memotong ke 300): secret di batas potongan lolos
                # kalau urutannya dibalik.
                last_error=f"{error_type}: {_scrub_secrets(str(exc))}",
            )
        log.error(
            "enrich_failed_recorded",
            url=url,
            error_type=error_type,
            job_id=job.id if job is not None else None,
        )
    except Exception as record_error:
        log.error(
            "enrich_failure_record_failed",
            url=url,
            original_error=str(exc)[:200],
            record_error=str(record_error)[:200],
        )


class _EnrichTask(Task):  # type: ignore[misc]
    """`on_failure` jalan SEKALI di kegagalan FINAL (retry habis / gak
    di-retry), bukan tiap percobaan."""

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        # `exc` dari Celery sudah "dibuat pickleable": exception dgn constructor
        # rumit (openai.*) turun ke kelas dasarnya (`AuthenticationError` ->
        # `OpenAIError`). Tipe ASLI ada di `einfo.type`.
        original = getattr(einfo, "type", None) or type(exc)
        _record_failed_job(kwargs, exc, original.__name__)


@app.task(bind=True, base=_EnrichTask, name="enrich.article", queue="enrich")
def enrich_article(
    self: Any,
    *,
    title: str,
    url: str,
    posted_on: str | None,
    source: str,
    scraper_id: str | None,
    replay: bool = False,
    alert: bool | None = None,
) -> dict[str, object]:
    """`replay=True` (artikel yang gagal di-enrich dikirim ulang, `send_enrich_task`): disimpan
    tanpa alert Telegram. `alert` (bila bukan None) menimpa bawaan itu, mis. replay otomatis yang
    masih segar. Keduanya hanya dikirim bila perlu, jadi pesan lama di antrian tetap valid."""
    from cti_core.db.engine import sync_session
    from cti_enrich.pipeline import run_pipeline

    parsed_posted_on = datetime.date.fromisoformat(posted_on) if posted_on else None
    content_kind, default_relevance, tlp, pap = _relevance_for(scraper_id)

    try:
        with sync_session() as session:
            # `sync_session()` commit otomatis pas keluar `with` tanpa
            # exception (lihat db/engine.py) -- gak perlu commit manual di sini.
            outcome = run_pipeline(
                title=title,
                url=url,
                posted_on=parsed_posted_on,
                source=source,
                scraper_id=scraper_id,
                session=session,
                alert=alert if alert is not None else not replay,
                content_kind=content_kind,
                default_relevance=default_relevance,
                tlp=tlp,
                pap=pap,
            )
    except _TRANSIENT_ERRORS as e:
        log.warning(
            "enrich_transient_error_retrying",
            url=url,
            error_type=type(e).__name__,
            attempt=self.request.retries + 1,
        )
        raise self.retry(
            exc=e, countdown=_backoff_s(self.request.retries), max_retries=_MAX_RETRIES_TRANSIENT
        ) from e

    log.info(
        "enrich_task_done",
        url=url,
        accepted=outcome.accepted,
        news_type=outcome.news_type,
        pending_job_id=outcome.pending_job_id,
    )
    return {"accepted": outcome.accepted, "news_type": outcome.news_type}


@app.task(name="enrich.llm", queue="enrich", max_retries=0)
def enrich_llm(job_id: int, decision: str | None = None) -> str:
    """Satu job `enrich_jobs` (P7g): LLM classify/TTP yang tertunda, atau keputusan analis
    (`decision="accept"|"reject"`). TANPA retry Celery: kegagalan dicatat di baris job (jadwal
    ulang gateway, batas JSON, `failed`) dan dispatcher mengirimnya lagi saat jatuh tempo.
    Return outcome `run_job` (`done`/`duplicate`/`gone`/`retry`/`failed`)."""
    from cti_enrich.jobs import run_job

    outcome = run_job(
        job_id,
        decision=cast(Literal["accept", "reject"] | None, decision),
        relevance_for=_relevance_for,
    )
    log.info("enrich_llm_done", job_id=job_id, decision=decision, outcome=outcome)
    return outcome
