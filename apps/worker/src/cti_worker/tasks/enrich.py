"""Task `enrich.article` -- gantiin tulis-langsung `_article_sink` (Fase 3).
`fetch()` scraper mana pun yang nge-`yield` `ArticleItem` sekarang mendarat
di sini via `send_task`, bukan `ArticleRepo.upsert()` langsung -- lihat
`cti_scraper.sinks._article_sink` (Fase 6), kontrak "tipe apa masuk situ"
gak berubah, cuma titik tulisnya pindah dari sink SINKRON ke task ASINKRON.

Import `cti_enrich` (spaCy/sumy) LAZY di dalam fungsi -- baca docstring
`cti_worker.celery_app` soal kenapa (worker scrape-only, image tanpa extra
`nlp`, tetep bisa start walau task ini gak pernah beneran dia jalanin).

Kebijakan kegagalan (Fase 10.A2) -- SATU prinsip: artikel yang sudah lolos
dedup (`scraper_seen` udah di-commit pas `send_task`) TIDAK BOLEH hilang tanpa
jejak. Tiga jalur:

1. **Transien** (LLM mati/timeout/5xx/429-bukan-kuota, koneksi DB putus,
   jaringan): retry sampai 6x, backoff eksponensial 30s -> 10 mnt (+jitter),
   total ~30 menit -- cukup buat gateway LLM yang restart/gangguan singkat.
2. **JSON rusak** (`json.JSONDecodeError` yang lolos dari retry internal
   `classify()`): 2x retry, lebih pelit karena tiap retry = sampai 3 panggilan
   LLM dan kegagalan JSON yang PERSISTEN jarang sembuh sendiri.
3. **Gagal permanen** (retry habis, atau error yang gak bakal sembuh:
   401/kuota abis/bug): `on_failure` nulis ke `rejected_articles` dengan
   `reason="[enrichment_failed] ..."` -> muncul di halaman Filtered Articles,
   bisa di-restore analis. Kalau artikelnya SUDAH tersimpan (gagal SESUDAH
   `persist`, mis. Telegram down) gak ada yang dicatat -- gak ada yang hilang.

`OpenAIQuotaExhausted` SENGAJA gak di-retry -- kuota abis gak pulih dalam
hitungan detik, retry cuma nge-spam queue; langsung dicatat, butuh tindakan
manusia."""

from __future__ import annotations

import datetime
import json
import random
from typing import Any

import httpx
import openai
import sqlalchemy.exc
import structlog
from celery import Task
from cti_core.llm.client import EmptyLLMResponse

from cti_worker.celery_app import app

log = structlog.get_logger()

_TRANSIENT_ERRORS = (
    openai.APIConnectionError,  # termasuk APITimeoutError
    openai.InternalServerError,  # 5xx dari gateway/provider
    openai.RateLimitError,  # 429 -- yang KUOTA sudah jadi OpenAIQuotaExhausted di stage
    EmptyLLMResponse,  # 200 tanpa `choices` (openrouter/free saat upstream gagal)
    httpx.TransportError,
    sqlalchemy.exc.OperationalError,  # koneksi DB putus / server restart
    sqlalchemy.exc.InterfaceError,
)
_MAX_RETRIES_TRANSIENT = 6
_MAX_RETRIES_JSON = 2


def _backoff_s(retries: int) -> float:
    """30s, 60s, 120s, ... maks 600s, +0-25% jitter (biar ratusan task yang
    gagal barengan gak nyerbu gateway yang baru pulih di detik yang sama)."""
    return float(min(600, 30 * 2**retries)) * (1 + random.random() * 0.25)


def _scrub_secrets(text: str) -> str:
    """Buang secret yang DIKONFIGURASI dari teks error sebelum masuk DB/UI:
    provider kadang ngecho (sebagian) API key di pesan errornya."""
    try:
        from cti_core.runtime_secrets.overlay import scrub_candidates

        secrets = scrub_candidates()
    except Exception:  # settings gak bisa dimuat: jangan sampai gagal nyatet gara-gara ini
        return text
    for secret in secrets:
        text = text.replace(secret, "***")
    return text


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


def _failure_kind(error_class: type[BaseException]) -> str:
    """Jenis kegagalan FINAL untuk `rejected_articles.failure_kind`, mengikuti kebijakan retry."""
    if issubclass(error_class, json.JSONDecodeError):
        return "json"
    if issubclass(error_class, _TRANSIENT_ERRORS):
        return "transient"
    return "permanent"


def _record_enrichment_failure(
    kwargs: dict[str, Any],
    exc: BaseException,
    error_type: str | None = None,
    failure_kind: str = "permanent",
) -> None:
    """Catat artikel yang gagal di-enrich ke `rejected_articles`. BEST-EFFORT:
    gagal nulis catatan ini gak boleh nutupi kegagalan aslinya (cuma di-log)."""
    url = kwargs.get("url", "?")
    try:
        from cti_core.db.engine import sync_session
        from cti_core.db.models.article import Article, RejectedArticle
        from cti_core.db.repositories.article import RejectedArticleRepo
        from cti_core.urlkit import url_hash
        from sqlalchemy import func, select

        with sync_session() as session:
            exists = session.scalar(select(Article.id).where(Article.url_hash == url_hash(url)))
            if exists is not None:
                # Gagal SESUDAH persist (mis. alert Telegram) -- artikelnya aman.
                log.error("enrich_failed_after_persist", url=url, error=str(exc)[:300])
                return
            posted = kwargs.get("posted_on")
            RejectedArticleRepo(session).upsert(
                url=url,
                title=kwargs.get("title", ""),
                source=kwargs.get("source", ""),
                scraper_id=kwargs.get("scraper_id"),
                posted_on=datetime.date.fromisoformat(posted) if posted else None,
                # Scrub SEBELUM dipotong: secret di batas 300 karakter lolos kalau tidak.
                reason=(
                    f"[enrichment_failed] {error_type or type(exc).__name__}: "
                    f"{_scrub_secrets(str(exc))[:300]}"
                ),
                failure_kind=failure_kind,
            )
            waiting = session.scalar(
                select(func.count())
                .select_from(RejectedArticle)
                .where(RejectedArticle.failure_kind.is_not(None))
            )
        error_name = error_type or type(exc).__name__
        log.error("enrich_failed_recorded", url=url, error_type=error_name)
        _alert_enrichment_failure(error_name, _scrub_secrets(str(exc))[:200], waiting or 0)
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
        _record_enrichment_failure(kwargs, exc, original.__name__, _failure_kind(original))


@app.task(bind=True, base=_EnrichTask, name="enrich.article", queue="enrich")
def enrich_article(
    self: Any,
    *,
    title: str,
    url: str,
    posted_on: str | None,
    source: str,
    scraper_id: str | None,
) -> dict[str, object]:
    from cti_core.db.engine import sync_session
    from cti_enrich.pipeline import run_pipeline

    parsed_posted_on = datetime.date.fromisoformat(posted_on) if posted_on else None

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
            )
    except json.JSONDecodeError as e:
        raise self.retry(
            exc=e, countdown=_backoff_s(self.request.retries), max_retries=_MAX_RETRIES_JSON
        ) from e
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
    )
    return {"accepted": outcome.accepted, "news_type": outcome.news_type}
