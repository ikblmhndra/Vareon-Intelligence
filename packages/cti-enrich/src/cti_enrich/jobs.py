"""Job runner `enrich_jobs` (P7g persist-first, spec 4.3): kerja LLM yang tertunda dijalankan di
sini, dipanggil task `enrich.llm` (antrian `enrich`) yang dikirim dispatcher atau aksi analis.

Aturan utamanya: panggilan LLM terjadi TANPA sesi/transaksi terbuka. Dulu classify (sampai 144
detik saat gateway lambat) memegang kunci URL dan koneksi DB sepanjang panggilan. Sekarang:

1. Sesi 1 membaca job (dan, untuk baris tanpa teks, menjalankan `prepare` di bawah kunci URL,
   lalu menyimpan teks + konteksnya ke job supaya kegagalan gateway berikutnya tidak fetch ulang).
2. LLM dipanggil tanpa sesi.
3. Sesi 2 mengunci job (`FOR UPDATE SKIP LOCKED`). Job hilang/terkunci = pihak lain (kiriman
   kedua karena lease habis, keputusan analis, artikel dihapus) sudah menang -> `gone`, no-op.
   Job dihapus di transaksi yang SAMA dengan hasilnya, jadi job dan hasilnya tidak pernah
   tercatat dua kali (Review Focus 2/3).

Kegagalan tidak di-retry Celery: gateway (5xx, timeout, 429, respons kosong, kuota, 400/401/
403/404) = `attempts+1` dan jatuh tempo lagi dengan jeda `min(60, 2^attempts)` menit tanpa batas
(gateway akan pulih; breaker P7g menahan laju kirimnya); JSON rusak = `json_failures+1`, pada
ke-3 job `failed` (job `ttp` malah dihapus dan artikel `llm_ttp_status='failed'`: TTP Tier 1-nya
tetap); error lain = `failed` langsung supaya bug tidak berputar diam-diam. `last_error` selalu
disamarkan dari secret dulu (`scrub_secrets`), baru dipotong repo ke 300 karakter.

`cti_enrich` tidak boleh mengimpor `cti_scraper` maupun `cti_alerts`, jadi worker menyuntikkan
`relevance_for` (marking/relevansi bawaan sumber untuk baris migrasi yang `context`-nya kosong)
dan `on_failed` (alert Telegram saat job menjadi `failed`)."""

from __future__ import annotations

import dataclasses
import datetime
import json
from collections.abc import Callable
from typing import Literal, cast

import httpx
import openai
import sqlalchemy.exc
import structlog
from cti_core.db.engine import sync_session
from cti_core.db.models.article import Article
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.repositories.article import ArticleRepo, apply_ttps
from cti_core.db.repositories.assessment import apply_assessments
from cti_core.db.repositories.enrich_job import EnrichJobRepo
from cti_core.db.repositories.story import StoryRepo
from cti_core.db.repositories.ttp_catalog import load_catalog
from cti_core.llm.breaker import is_fresh
from cti_core.llm.client import EmptyLLMResponse
from cti_core.runtime_secrets.overlay import scrub_secrets
from sqlalchemy.orm import Session

from cti_enrich.pipeline import (
    PipelineOutcome,
    Prepared,
    _known_article,
    complete,
    prepare,
    tier0_classify,
)
from cti_enrich.stages.classify import ClassifyResult, OpenAIQuotaExhausted, classify
from cti_enrich.stages.extract_ttps import extract_ttps, normalize_ttp_result, verify_evidence
from cti_enrich.story.attach import classify_from_story
from cti_enrich.tier1.merge import merge_ttps
from cti_enrich.tier1.ttps import SourcedTechnique, TtpSource

log = structlog.get_logger()

JobOutcome = Literal["done", "duplicate", "gone", "retry", "failed"]
Decision = Literal["accept", "reject"]
RelevanceFor = Callable[[str | None], tuple[str | None, str, str, str]]
"""`scraper_id` -> `(content_kind, default_relevance, tlp, pap)` (worker: `_relevance_for`)."""
OnFailed = Callable[[str, str], None]
"""`(judul, last_error)` saat job menjadi `failed` (worker: alert Telegram, Task 5)."""

GATEWAY_ERRORS: tuple[type[BaseException], ...] = (
    openai.APIConnectionError,  # termasuk APITimeoutError
    openai.InternalServerError,
    openai.RateLimitError,
    EmptyLLMResponse,
    OpenAIQuotaExhausted,  # kuota/kredit habis: pulih sendiri sesudah diisi ulang
    # 400/401/403/404 = konfigurasi (model salah, key dicabut): menunggu admin memperbaikinya,
    # bukan bug per artikel. Dulu `_CONFIG_ERRORS` di task `enrich.article`.
    openai.BadRequestError,
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
)
"""Error gateway LLM: dijadwalkan ulang tanpa batas (`record_gateway_failure`)."""

RESCHEDULE_ERRORS: tuple[type[BaseException], ...] = (
    sqlalchemy.exc.OperationalError,  # koneksi DB putus / server restart
    sqlalchemy.exc.InterfaceError,
    httpx.TransportError,  # jaringan saat fetch (`prepare`)
)
"""Error DB/jaringan (R9): dijadwalkan ulang seperti gateway, bukan `failed` -- bukan bug per
job. Kalau DB masih mati saat mencatatnya, task raise dan lease dispatcher mengirim ulang."""

_ANALYST = "analyst"


class DecisionNotAllowed(ValueError):
    """Keputusan analis untuk job `ttp` (API menolaknya dengan 409). Salah pakai, bukan kegagalan
    job: diteruskan ke pemanggil tanpa menandai job `failed`."""


_MERGED_SOURCES = ("explicit", "keyword", "llm")


def run_job(
    job_id: int,
    *,
    decision: Decision | None = None,
    now: datetime.datetime | None = None,
    on_failed: OnFailed | None = None,
    relevance_for: RelevanceFor | None = None,
) -> JobOutcome:
    """Jalankan satu job. `decision` (analis, hanya job `classify`) menggantikan vonis LLM:
    `accept` = relevan dengan vonis insiden dari aturan Tier 1, `reject` = `persist_rejected`
    beralasan `analyst`. `now` untuk kesegaran alert dan jadwal ulang (test)."""
    now = now or datetime.datetime.now(datetime.UTC)
    try:
        return _run(job_id, decision, now, relevance_for)
    except (*GATEWAY_ERRORS, *RESCHEDULE_ERRORS) as e:
        return _record_failure(job_id, now, e, "gateway", on_failed)
    except json.JSONDecodeError as e:
        return _record_failure(job_id, now, e, "json", on_failed)
    except DecisionNotAllowed:
        raise
    except Exception as e:
        log.error("enrich_job_unexpected_error", job_id=job_id, exc_info=True)
        return _record_failure(job_id, now, e, "other", on_failed)


def _run(
    job_id: int,
    decision: Decision | None,
    now: datetime.datetime,
    relevance_for: RelevanceFor | None,
) -> JobOutcome:
    with sync_session() as session:
        job = session.get(EnrichJob, job_id, populate_existing=True)
        if job is None:
            log.info("enrich_job_gone", job_id=job_id)
            return "gone"
        if job.state == "failed" and decision is None:
            # Menunggu analis (retry mengembalikannya ke `pending`); kiriman basi diabaikan.
            log.info("enrich_job_waits_for_analyst", job_id=job_id)
            return "failed"
        kind = job.kind
        if kind == "ttp":
            if decision is not None:
                raise DecisionNotAllowed(f"keputusan analis hanya untuk job classify ({job_id})")
            text = job.input_text or ""
        else:
            started = _start_classify(session, job, decision, now, relevance_for)
            if isinstance(started, str):
                return started
            prepared, verdict = started
    if kind == "ttp":
        return _finish_ttp(job_id, text)
    if verdict is None:
        verdict = classify(prepared.title)  # tanpa sesi terbuka
    return _finish_classify(job_id, prepared, verdict, now)


# ── classify ─────────────────────────────────────────────────────────────────────────────


def _source_fields(
    job: EnrichJob, relevance_for: RelevanceFor | None
) -> tuple[str | None, str, str, str]:
    """`(content_kind, default_relevance, tlp, pap)`: dari `context`, atau dari `relevance_for`
    untuk baris migrasi yang `context`-nya kosong (R7), atau bawaan `run_pipeline`."""
    ctx = job.context or {}
    if "default_relevance" not in ctx and relevance_for is not None:
        return relevance_for(job.scraper_id)
    return (
        ctx.get("content_kind"),
        ctx.get("default_relevance") or "classify",
        ctx.get("tlp") or "clear",
        ctx.get("pap") or "clear",
    )


def _start_classify(
    session: Session,
    job: EnrichJob,
    decision: Decision | None,
    now: datetime.datetime,
    relevance_for: RelevanceFor | None,
) -> JobOutcome | tuple[Prepared, ClassifyResult | None]:
    """Sesi 1. Return outcome akhir, atau `(Prepared, vonis)` dengan vonis `None` = perlu LLM."""
    if job.input_text is None:
        # SKIP LOCKED: baris yang terkunci sebentar (klaim dispatcher, pencatatan gagal paralel)
        # terbaca "gone" dan vonis LLM yang sudah jadi dibuang; job jalan lagi setelah lease habis,
        # biayanya satu panggilan LLM.
        locked = EnrichJobRepo(session).get_for_update(job.id)
        if locked is None:
            return "gone"
        started = _prepare_first(session, locked, decision, now, relevance_for)
        if isinstance(started, str):
            return started
        prepared = started
    else:
        content_kind, default_relevance, tlp, pap = _source_fields(job, relevance_for)
        prepared = dataclasses.replace(
            Prepared.from_job(job),
            content_kind=content_kind,
            default_relevance=default_relevance,
            tlp=tlp,
            pap=pap,
        )
    return prepared, _verdict_without_llm(session, prepared, decision)


def _fresh(job: EnrichJob, now: datetime.datetime) -> bool:
    """Layak alert? Tanpa `posted_on` pakai `created_at` job (kedatangan live = baru, baris migrasi
    membawa `rejected_at` lamanya = basi); sebelum P7g artikel tanpa tanggal selalu di-alert."""
    return is_fresh(job.posted_on or job.created_at.date(), now)


def _prepare_first(
    session: Session,
    job: EnrichJob,
    decision: Decision | None,
    now: datetime.datetime,
    relevance_for: RelevanceFor | None,
) -> JobOutcome | Prepared:
    """Job tanpa teks (baris migrasi, `on_failure`): bagian depan pipeline dulu. Teks + konteks
    disimpan ke job (commit di akhir sesi 1), jadi gagal gateway sesudahnya tidak fetch ulang.
    Kalau relevansinya ternyata sudah diketahui tanpa LLM (Tier 0, warisan story, gate),
    selesaikan di sini selagi kunci URL dipegang."""
    repo = EnrichJobRepo(session)
    if _known_article(session, job.url) is not None:
        # Diperiksa SEBELUM `prepare` supaya `seen_count` artikel tidak naik: ini bukan
        # kedatangan baru (Review Focus 4: stub yang sudah di-restore).
        repo.delete(job)
        log.info("enrich_job_duplicate", job_id=job.id, url=job.url)
        return "duplicate"
    content_kind, default_relevance, tlp, pap = _source_fields(job, relevance_for)
    result = prepare(
        title=job.title,
        url=job.url,
        posted_on=job.posted_on,
        source=job.source,
        scraper_id=job.scraper_id,
        session=session,
        content_kind=content_kind,
        default_relevance=default_relevance,
        tlp=tlp,
        pap=pap,
        resume_job_id=job.id,
    )
    if isinstance(result, PipelineOutcome):
        # Tidak terjadi (artikel sudah diperiksa di atas, job ini dikecualikan); dijaga saja.
        repo.delete(job)
        return "duplicate"
    if result.classify_result is not None and decision is None:
        repo.delete(job)
        complete(result, result.classify_result, session=session, alert=_fresh(job, now))
        log.info("enrich_job_done", job_id=job.id, kind="classify", llm=False)
        return "done"
    job.input_text = result.text
    job.context = result.to_context()
    session.flush()
    return result


def _verdict_without_llm(
    session: Session, prepared: Prepared, decision: Decision | None
) -> ClassifyResult | None:
    """Vonis yang tidak butuh LLM: keputusan analis, Tier 0, atau lead story yang sudah
    di-classify SESUDAH job ini dibuat (spec 5: follow-up menunggu lead-nya)."""
    if decision is not None:
        return ClassifyResult(
            related_cyber=decision == "accept", reason=_ANALYST, audit={"skipped": _ANALYST}
        )
    if prepared.default_relevance == "always":
        return tier0_classify(prepared.content_kind)
    if prepared.story is not None:
        data, lead_article_id = StoryRepo(session).get_inherit(prepared.story.story_id)
        if data is not None:
            return classify_from_story(
                data,
                story_id=prepared.story.story_id,
                rule=prepared.story.rule,
                lead_article_id=lead_article_id,
            )
    return None


def _finish_classify(
    job_id: int, prepared: Prepared, verdict: ClassifyResult, now: datetime.datetime
) -> JobOutcome:
    """Sesi 2: kunci job, cek ulang artikel di bawah kunci URL, lalu `complete`. Job dihapus
    SEBELUM `complete` supaya ikut commit-nya (jalur terima commit di dalam `complete`, jalur
    tolak di akhir sesi ini)."""
    with sync_session() as session:
        repo = EnrichJobRepo(session)
        job = repo.get_for_update(job_id)
        if job is None:
            log.info("enrich_job_gone", job_id=job_id, stage="persist")
            return "gone"
        if _known_article(session, prepared.url) is not None:
            # Termasuk job `failed` yang ditulis `on_failure` yang balapan dengan task paralel.
            repo.delete(job)
            log.info("enrich_job_duplicate", job_id=job_id, url=prepared.url)
            return "duplicate"
        repo.delete(job)
        complete(prepared, verdict, session=session, alert=_fresh(job, now))
    log.info("enrich_job_done", job_id=job_id, kind="classify", accepted=verdict.related_cyber)
    return "done"


# ── ttp ──────────────────────────────────────────────────────────────────────────────────


def _finish_ttp(job_id: int, text: str) -> JobOutcome:
    """LLM TTP tanpa sesi, lalu gabung ke mention artikel. Mention di luar `explicit`/`keyword`/
    `llm` (`analyst`, `legacy`) TIDAK ditulis sama sekali: barisnya tidak dihapus
    (`only_methods`) dan ID-nya tidak dikirim ke upsert (yang akan menimpa method/alias/bukti).
    Sisanya digabung `merge_ttps` (explicit > llm > keyword) dan ditulis `apply_ttps` (P7c). P6
    dihitung ulang (poin prioritas menghitung TTP LLM). Tanpa alert: alert sudah keluar."""
    result = extract_ttps(text)
    with sync_session() as session:
        repo = EnrichJobRepo(session)
        job = repo.get_for_update(job_id)
        if job is None:
            log.info("enrich_job_gone", job_id=job_id, stage="persist")
            return "gone"
        article = session.get(Article, job.article_id) if job.article_id is not None else None
        if article is None:
            repo.delete(job)
            return "gone"
        if result.techniques:
            result = normalize_ttp_result(result, load_catalog(session))
            result = verify_evidence(result, text)
        current = [m for m in article.mentions_of("attack-pattern") if m.entity.external_id]
        untouched = {m.entity.external_id for m in current if m.method not in _MERGED_SOURCES}
        tier1 = [
            SourcedTechnique(
                cast(str, m.entity.external_id),
                m.entity.name,
                cast(TtpSource, m.method),
                m.evidence or "",
            )
            for m in current
            if m.method in _MERGED_SOURCES
        ]
        merged = [t for t in merge_ttps(result, tier1) if t.ttp_id not in untouched]
        apply_ttps(article, merged, only_methods=_MERGED_SOURCES)
        ArticleRepo(session).touch_entity_seen(article)
        article.llm_ttp_status = "done"
        session.flush()
        apply_assessments(session, [article.id])
        repo.delete(job)
    log.info("enrich_job_done", job_id=job_id, kind="ttp", techniques=len(result.techniques))
    return "done"


# ── kegagalan ────────────────────────────────────────────────────────────────────────────


def _record_failure(
    job_id: int,
    now: datetime.datetime,
    exc: BaseException,
    kind: Literal["gateway", "json", "other"],
    on_failed: OnFailed | None,
) -> JobOutcome:
    """Catat kegagalan di sesi baru (sesi yang gagal sudah di-rollback). Job yang sudah hilang
    (dihapus pihak lain, atau error terjadi SESUDAH commit hasilnya, mis. alert Telegram) =
    `gone`."""
    # Scrub SEBELUM dipotong (repo memotong ke 300): secret di batas potongan lolos kalau
    # urutannya dibalik.
    error = f"{type(exc).__name__}: {scrub_secrets(str(exc))}"
    with sync_session() as session:
        repo = EnrichJobRepo(session)
        job = repo.get_for_update(job_id)
        if job is None:
            log.warning("enrich_job_error_job_gone", job_id=job_id, error=error[:300])
            return "gone"
        if kind == "gateway":
            repo.record_gateway_failure(job, now, error)
            log.warning("enrich_job_gateway_error", job_id=job_id, attempts=job.attempts)
            return "retry"
        if kind == "json" and not repo.record_json_failure(job, now, error):
            log.warning("enrich_job_json_error", job_id=job_id, failures=job.json_failures)
            return "retry"
        if kind == "json" and job.kind == "ttp":
            # TTP itu pengayaan opsional: artikel tetap dengan TTP Tier 1, job selesai.
            article = session.get(Article, job.article_id) if job.article_id is not None else None
            if article is not None:
                article.llm_ttp_status = "failed"
            repo.delete(job)
            log.warning("enrich_ttp_job_gave_up", job_id=job_id, article_id=job.article_id)
            return "failed"
        if kind == "other":
            repo.mark_failed(job, error)
        title, last_error = job.title, job.last_error or error
    log.error("enrich_job_failed", job_id=job_id, error=last_error)
    if on_failed is not None:
        try:
            on_failed(title, last_error)
        except Exception as alert_error:  # best effort: kegagalan aslinya sudah tercatat
            log.error("enrich_job_failed_alert_failed", error=str(alert_error)[:200])
    return "failed"
