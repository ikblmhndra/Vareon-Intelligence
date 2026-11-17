"""Job `tweet` (spec tweet-llm-cost, Part A "Worker"): klasifikasi tweet yang dulu jalan di
`fetch()` scraper (`tweet_alerts_*`, `monitor_x`) sekarang jalan di sini, dipanggil `jobs.run_job`
(task `enrich.llm`, `worker-nlp`) seperti job `classify` artikel.

Urutan:
1. Sesi 1: tweet sudah ada di `tweets` (disimpan scraper/job lain) -> job dihapus, `duplicate`,
   tanpa LLM. `verdict_for` (default `gate_verdict`, gate relevansi lokal Part C) boleh memberi
   vonis tanpa LLM.
2. LLM (`classify_tweet`) TANPA sesi terbuka, sama dengan aturan `jobs.py`.
3. Sesi 2: kunci job (`SKIP LOCKED`; hilang = pihak lain menang -> `gone`), catat vonis di
   `tweet_verdicts` (semua tweet, termasuk yang ditolak: bahan latih model tweet), simpan ke
   `tweets` bila relevan, hapus job, commit.
4. Sesudah commit, bila `notify` dan tweet masih segar: satu notice Telegram per topik
   (`route_tweet`). Commit dulu baru kirim (seperti `pipeline.complete`): crash di antaranya
   menghilangkan alert, bukan menggandakannya. Gagal kirim satu topik di-log dan topik lain tetap
   dikirim; tidak membatalkan tweet yang tersimpan.

Error LLM/DB TIDAK ditangkap di sini: `jobs.run_job` yang mencatatnya (gateway/kuota = jadwal
ulang, JSON rusak 3x = `failed`, lainnya `failed`), satu jalur kegagalan untuk semua jenis job.

Teks pesan (`msg_data` di `routing` dan `notice_text`) dibangun SCRAPER saat scan-nya masih ada
(`tweet_alerts.build_message` butuh `ScoreResult`, yang tidak disimpan di job). Akibatnya teks
pesan dibekukan saat scrape; sama dengan perilaku lama (Ruling 4)."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any, Literal

import structlog
from cti_alerts.telegram import send_alert
from cti_core.db.engine import sync_session
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.repositories.enrich_job import EnrichJobRepo
from cti_core.db.repositories.tweet import TweetRepo, TweetVerdictRepo
from sqlalchemy.orm import Session

from cti_enrich.stages.classify import TWEET_PROMPT_VERSION, ClassifyResult, classify_tweet
from cti_enrich.stages.relevance import gated_classify, run_relevance
from cti_enrich.stages.tier1 import run_tier1
from cti_enrich.tweet_routing import TweetRoutingInput, route_tweet

log = structlog.get_logger()

TWEET_ALERT_MAX_AGE = datetime.timedelta(hours=6)
"""Tweet di-alert hanya bila `posted_on`-nya paling lama segini sebelum job selesai. Jendela
pencarian scraper paling lama 2 jam, jadi operasi normal jauh di dalamnya; tweet yang lebih tua
(job yang tertahan breaker lama) tetap disimpan untuk X Intel, tanpa Telegram."""

Verdict = tuple[ClassifyResult | None, str, dict[str, Any] | None]
VerdictFor = Callable[[Session, EnrichJob], Verdict]
"""Langkah sebelum LLM, dipanggil di sesi 1: `(vonis, source, audit relevansi)`. Vonis `None` =
tanya LLM (`source` diabaikan, jadi `llm`); audit relevansinya tetap dicatat (mode shadow).
Default = `gate_verdict` (gate relevansi tweet, Part C)."""

_LLM = "llm"
_GATE = "gate"


def gate_verdict(session: Session, job: EnrichJob) -> Verdict:
    """Gate relevansi tweet (spec tweet-llm-cost, Part C), aturan sama dengan artikel (P5): hanya
    `threat_news` dalam band di luar sampel audit yang melewati LLM; luar band, sampel audit,
    shadow dan reject selalu ke LLM, jadi gate tidak pernah diam-diam menolak tweet.

    Tweet yang lolos gate mengambil industri dan vonis insiden dari Tier 1 (`incident_source`
    "rule", seperti artikel yang lolos gate). Tier 1 tidak punya negara: `victim_countries` dan
    `actor_countries` kosong untuk tweet ini (kerugian yang diterima spec). Kegagalan model/Tier 1
    sudah ditangani `run_relevance`/`run_tier1` (jatuh ke LLM / hasil kosong)."""
    from cti_core.config import get_settings

    text = job.input_text or ""
    relevance = run_relevance(
        session, title=text, url=job.url, cfg=get_settings().relevance, kind="tweet"
    )
    if relevance is None:
        return None, _LLM, None
    audit = relevance.to_audit()
    if relevance.decision.decision != "gated":
        return None, _LLM, audit
    tier1 = run_tier1(session=session, title=text, text=text, victim_name=None)
    result = gated_classify(relevance)
    result.industries_impacted = tier1.industries
    result.confirmed_incident = tier1.incident.confirmed if tier1.incident is not None else None
    audit["incident_source"] = "rule"
    return result, _GATE, audit


TweetOutcome = Literal["done", "duplicate", "gone"]


def run_tweet_job(
    job_id: int, now: datetime.datetime, *, verdict_for: VerdictFor = gate_verdict
) -> TweetOutcome:
    """Jalankan satu job `tweet`. Outcome-nya bagian dari `jobs.JobOutcome`."""
    with sync_session() as session:
        job = session.get(EnrichJob, job_id, populate_existing=True)
        if job is None:
            log.info("enrich_job_gone", job_id=job_id, kind="tweet")
            return "gone"
        tweet_id = str(job.context["tweet"]["tweet_id"])
        if TweetRepo(session).exists(tweet_id):
            return _drop_duplicate(session, job_id, tweet_id)
        text = job.input_text or ""
        result, source, relevance = verdict_for(session, job)
    if result is None:
        result, source = classify_tweet(text), _LLM  # tanpa sesi terbuka
    return _finish(job_id, text, result, source, relevance, now)


def _drop_duplicate(session: Session, job_id: int, tweet_id: str) -> TweetOutcome:
    repo = EnrichJobRepo(session)
    locked = repo.get_for_update(job_id)
    if locked is None:
        return "gone"
    repo.delete(locked)
    log.info("enrich_job_duplicate", job_id=job_id, kind="tweet", tweet_id=tweet_id)
    return "duplicate"


def _finish(
    job_id: int,
    text: str,
    result: ClassifyResult,
    source: str,
    relevance: dict[str, Any] | None,
    now: datetime.datetime,
) -> TweetOutcome:
    """Sesi 2: vonis, baris `tweets`, hapus job, commit; lalu notice."""
    with sync_session() as session:
        repo = EnrichJobRepo(session)
        job = repo.get_for_update(job_id)
        if job is None:
            log.info("enrich_job_gone", job_id=job_id, kind="tweet", stage="persist")
            return "gone"
        ctx = job.context
        tweet = ctx["tweet"]
        tweet_id = str(tweet["tweet_id"])
        TweetVerdictRepo(session).record(
            tweet_id=tweet_id,
            text=text,
            related_cyber=result.related_cyber,
            source=source,
            prompt_version=TWEET_PROMPT_VERSION if source == _LLM else None,
            relevance=relevance,
        )
        posted = _posted(tweet, job)
        if result.related_cyber and tweet.get("author_username"):
            # Tanpa `author_username` tweet tidak diarsipkan (kolom NOT NULL) tapi tetap di-alert,
            # sama dengan perilaku `tweet_alerts` lama (Carry-forward E).
            inserted = TweetRepo(session).insert(
                tweet_id=tweet_id,
                url=tweet["url"],
                text=tweet["text"],
                source=job.scraper_id or job.source,
                author_username=tweet["author_username"],
                author_name=tweet.get("author_name"),
                author_avatar=tweet.get("author_avatar"),
                author_followers=tweet.get("author_followers"),
                posted_on=posted if tweet.get("posted_on") else None,
                lang=tweet.get("lang"),
                media_urls=tweet.get("media_urls") or [],
                scan_results=ctx.get("scan_results") or {},
                **llm_fields(result),
            )
            if inserted is None:
                # Disimpan pihak lain sejak sesi 1: alert-nya milik pihak itu.
                repo.delete(job)
                log.info("enrich_job_duplicate", job_id=job_id, kind="tweet", tweet_id=tweet_id)
                return "duplicate"
        repo.delete(job)
        notify = bool(ctx.get("notify")) and result.related_cyber
        routing, notice_text = ctx.get("routing") or {}, ctx.get("notice_text")
    log.info(
        "enrich_job_done", job_id=job_id, kind="tweet", source=source, related=result.related_cyber
    )
    if notify and now - posted <= TWEET_ALERT_MAX_AGE:
        _send_notices(job_id, routing, notice_text)
    return "done"


def _posted(tweet: dict[str, Any], job: EnrichJob) -> datetime.datetime:
    """Waktu posting tweet; tanpa itu `created_at` job (kedatangan live = baru)."""
    raw = tweet.get("posted_on")
    if not raw:
        return job.created_at
    posted = datetime.datetime.fromisoformat(raw)
    return posted if posted.tzinfo else posted.replace(tzinfo=datetime.UTC)


def _send_notices(job_id: int, routing: dict[str, Any], notice_text: str | None) -> None:
    if not notice_text or "msg_data" not in routing:
        # Job `notify=False` yang di-OR jadi `True` sesudah worker membaca context-nya
        # (balapan yang diterima), atau baris dari scraper versi lama.
        log.warning("tweet_notice_without_text", job_id=job_id)
        return
    for topic in route_tweet(TweetRoutingInput(**routing)):
        try:
            send_alert(topic, notice_text)
        except Exception:
            log.warning("tweet_notice_send_failed", job_id=job_id, topic=topic, exc_info=True)


def llm_fields(llm: ClassifyResult) -> dict[str, Any]:
    """Kolom LLM baris `tweets` dari vonis (dulu `_tweet_item.llm_fields` di scraper)."""
    return {
        "confidence_score": round(llm.confidence * 100) if llm.confidence else None,
        "confirmed_incident": bool(llm.confirmed_incident),
        "industries_impacted": llm.industries_impacted,
        "victim_countries": llm.victim_countries,
        "actor_countries": llm.actor_countries,
        "victim_name": llm.victim_name,
        "incident_confidence": (
            round(llm.incident_confidence * 100) if llm.incident_confidence is not None else None
        ),
        "incident_indicators": llm.incident_indicators,
    }
