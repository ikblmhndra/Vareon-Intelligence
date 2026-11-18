"""Task laporan periodik (Fase 10.E) -- gantiin job Rundeck `sendCounter`,
`trendingNewsToday`, `logbook`, `topCve`, logbook feeds bulanan (Excel inventaris sumber),
bagian laporan `trendingCve`, dan pasangan
`threatactorTrendGraylog`/`threatactorTrendTelegram`.

Pola tiap task: (1) baca DB di dalam `sync_session()`, (2) TUTUP sesi, (3) baru
kirim Telegram, (4) update state/counter di sesi baru HANYA kalau kirim sukses.
Urutan itu disengaja: Telegram gagal tidak boleh menghilangkan data (kode lama
mereset counter / mengosongkan file SEBELUM mengirim), dan koneksi DB tidak
ditahan selama panggilan jaringan lambat.

Jam laporan mengikuti `WorkerSettings.report_utc_offset_hours` (lihat `beat.py`).
Semua task menerima `day` (ISO) opsional supaya laporan yang terlewat bisa diulang
manual: `celery -A cti_worker.celery_app call report.daily_counters --queue notify
--args='["2026-09-25"]'`. `--queue notify` wajib: `call` memakai `send_task` yang tidak
membaca `queue=` dekorator, jadi tanpa itu pesan jatuh ke antrean `celery` yang tidak
dikonsumsi worker mana pun.
Tanpa retry otomatis (sama filosofi `periodic.py`): gagal sekali, jadwal berikutnya
mencoba lagi; kegagalan kelihatan di log Celery, bukan ditelan.
"""

from __future__ import annotations

import datetime
from typing import Any

import httpx
import structlog
from cti_alerts.telegram import send_alert, send_document
from cti_core.config import get_settings
from cti_core.db.engine import sync_session
from cti_core.db.models.article import Article
from cti_core.db.models.report_state import SCOPE_NEWS, SCOPE_TWEET
from cti_core.db.repositories.report_state import CveMentionRepo, JobStateRepo
from cti_scraper.reference_data import techstack_names
from sqlalchemy import select

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_NOTIFY
from cti_worker.reports import (
    cve_digest,
    daily_counters,
    feeds_logbook,
    logbook,
    news_of_the_day,
    threat_actor_trend,
)
from cti_worker.reports.timeutil import local_now

log = structlog.get_logger()

LOGBOOK_STATE_KEY = "logbook.last_report_date"
FEEDS_LOGBOOK_STATE_KEY = "feeds_logbook.last_report_month"


def _today(day: str | None, offset: int) -> datetime.date:
    return datetime.date.fromisoformat(day) if day else local_now(offset).date()


# ── sendCounter ────────────────────────────────────────────────────────────────


@app.task(bind=True, name="report.daily_counters", queue=QUEUE_NOTIFY)
def report_daily_counters(self: Any, day: str | None = None) -> dict[str, object]:
    """Ringkasan + daftar judul related/unrelated hari ini -> topik `debug`."""
    offset = get_settings().worker.report_utc_offset_hours
    local_day = _today(day, offset)
    with sync_session() as session:
        counters = daily_counters.collect(session, local_day, offset)

    send_alert("debug", counters.message())
    for name, text in counters.files().items():
        send_document("debug", name, text)
    log.info("report_daily_counters_sent", day=str(local_day), scraped=counters.scraped)
    return {"day": str(local_day), "scraped": counters.scraped, "files": len(counters.files())}


# ── trendingNewsToday ────────────────────────────────────────────────────────────


@app.task(bind=True, name="report.news_of_the_day", queue=QUEUE_NOTIFY)
def report_news_of_the_day(self: Any, day: str | None = None) -> dict[str, object]:
    """Topik terpanas hari ini (GLOBAL dan APAC) -> dokumen JSON ke topik `notd`."""
    w = get_settings().worker
    local_day = _today(day, w.report_utc_offset_hours)
    sent: list[str] = []
    for category in news_of_the_day.CATEGORIES:
        with sync_session() as session:
            report = news_of_the_day.build(
                session,
                local_day,
                w.report_utc_offset_hours,
                category,
                max_titles=w.news_of_the_day_max_titles,
            )
        if report is None:
            log.info("news_of_the_day_no_articles", category=category, day=str(local_day))
            continue
        send_document("notd", report.filename, report.as_json(), report.caption)
        sent.append(category)
    return {"day": str(local_day), "sent": sent}


# ── logbook ──────────────────────────────────────────────────────────────────────


@app.task(bind=True, name="report.logbook", queue=QUEUE_NOTIFY)
def report_logbook(self: Any, day: str | None = None) -> dict[str, object]:
    """Tiap hari dicek; laporan dibuat kalau sudah `logbook_interval_days` sejak yang
    terakhir. Panggilan PERTAMA (belum ada tanggal terakhir) cuma mencatat hari ini
    -- laporan pertama 14 hari kemudian, sama dengan skrip lama."""
    w = get_settings().worker
    today = _today(day, w.report_utc_offset_hours)
    with sync_session() as session:
        state = JobStateRepo(session)
        last_raw = state.get(LOGBOOK_STATE_KEY)
        if last_raw is None:
            state.set(LOGBOOK_STATE_KEY, today.isoformat())
            return {"status": "initialized", "day": str(today)}
        last = datetime.date.fromisoformat(last_raw)
        if (today - last).days < w.logbook_interval_days:
            return {"status": "not_due", "last": last_raw}

        start = today - datetime.timedelta(days=w.logbook_interval_days)
        rows = session.execute(
            select(Article.news_type, Article.title, Article.url, Article.posted_on)
            .where(
                Article.posted_on >= start,
                Article.posted_on <= today,
                Article.news_type.in_(["global", "apac"]),
            )
            .order_by(Article.posted_on, Article.id)
        ).all()
        entries = [logbook.LogbookEntry(t.upper(), title, url, d) for t, title, url, d in rows]

    data = logbook.build(
        entries,
        start=start,
        end=today,
        signatories=logbook.Signatories(
            w.logbook_preparer_name,
            w.logbook_preparer_title,
            w.logbook_approver_name,
            w.logbook_approver_title,
        ),
    )
    send_document(
        "logbook", logbook.filename_for(start, today), data, logbook.caption(start, today)
    )
    with sync_session() as session:
        JobStateRepo(session).set(LOGBOOK_STATE_KEY, today.isoformat())
    log.info("report_logbook_sent", entries=len(entries), start=str(start), end=str(today))
    return {"status": "sent", "entries": len(entries)}


# ── logbook feeds (bulanan) ──────────────────────────────────────────────────────


@app.task(bind=True, name="report.feeds_logbook", queue=QUEUE_NOTIFY)
def report_feeds_logbook(self: Any, day: str | None = None) -> dict[str, object]:
    """Inventaris feed (Excel) ke topik `logbook`, sebulan sekali di hari terakhir bulan.

    Dua mode, sengaja dipisah: run TERJADWAL (tanpa `day`) hanya jalan di hari terakhir bulan
    dan memakai state `FEEDS_LOGBOOK_STATE_KEY` supaya beat yang menembak ulang tidak mengirim
    dua kali. Run MANUAL (`day` diisi) selalu mengirim periode 1 bulan itu s.d. `day` dan TIDAK
    membaca maupun menulis state, supaya uji coba di tengah bulan tidak menggugurkan laporan
    akhir bulan: `celery -A cti_worker.celery_app call report.feeds_logbook
    --queue notify --args='["2026-10-31"]'` (tanpa `--queue notify` pesan tidak pernah diambil)."""
    offset = get_settings().worker.report_utc_offset_hours
    manual = day is not None
    today = _today(day, offset)
    if not manual:
        if not feeds_logbook.is_last_day_of_month(today):
            return {"status": "not_due"}
        month = today.strftime("%Y-%m")
        with sync_session() as session:
            sent_month = JobStateRepo(session).get(FEEDS_LOGBOOK_STATE_KEY)
        if sent_month == month:
            return {"status": "already_sent", "month": month}

    start, end = feeds_logbook.period_for(today)
    with sync_session() as session:
        rows = feeds_logbook.collect(
            session, end=end, offset_hours=offset, now=datetime.datetime.now(datetime.UTC)
        )
    data = feeds_logbook.build(rows, start=start, end=end)
    send_document(
        "logbook", feeds_logbook.filename_for(end), data, feeds_logbook.caption(start, end)
    )
    if not manual:
        with sync_session() as session:  # SESUDAH kirim sukses
            JobStateRepo(session).set(FEEDS_LOGBOOK_STATE_KEY, end.strftime("%Y-%m"))
    log.info("report_feeds_logbook_sent", rows=len(rows), start=str(start), end=str(end))
    return {
        "status": "sent",
        "rows": len(rows),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "manual": manual,
    }


# ── topCve ───────────────────────────────────────────────────────────────────────


@app.task(bind=True, name="report.weekly_top_cve", queue=QUEUE_NOTIFY)
def report_weekly_top_cve(self: Any, day: str | None = None) -> dict[str, object]:
    """10 CVE paling banyak disebut artikel 7 hari terakhir -> `tech_stack`."""
    today = _today(day, get_settings().worker.report_utc_offset_hours)
    with sync_session() as session, httpx.Client() as client:
        digest = cve_digest.build_weekly(session, client, techstack_names(session), today=today)
    if digest is None:
        return {"status": "empty"}

    send_alert("tech_stack", digest.text)
    with sync_session() as session:
        CveMentionRepo(session).reset(SCOPE_NEWS, digest.cve_ids)  # SESUDAH kirim sukses
    return {"status": "sent", "cves": len(digest.cve_ids)}


# ── trendingCve (laporan 6 jam; pengumpulan mention tweet ada di scraper) ─────────


@app.task(bind=True, name="report.trending_cve", queue=QUEUE_NOTIFY)
def report_trending_cve(self: Any) -> dict[str, object]:
    """Top 10 CVE dari mention TWEET -> `tech_stack` kalau ada yang cocok tech stack,
    kalau tidak `tech_stack_unrelated` DAN `vendor_report` (perilaku `trendingCve` lama)."""
    with sync_session() as session, httpx.Client() as client:
        mentions = CveMentionRepo(session).top(SCOPE_TWEET, limit=10)
        digest = cve_digest.build_trending(mentions, client, techstack_names(session))
    if digest is None:
        return {"status": "empty"}

    if digest.any_applicable:
        send_alert("tech_stack", digest.text)
    else:
        send_alert("tech_stack_unrelated", digest.text)
        send_alert("vendor_report", digest.text)
    with sync_session() as session:
        CveMentionRepo(session).reset_scope(SCOPE_TWEET)  # laporan lama mengosongkan semuanya
    return {"status": "sent", "cves": len(digest.cve_ids)}


# ── threatactorTrendGraylog + threatactorTrendTelegram ────────────────────────────


@app.task(bind=True, name="report.weekly_threat_actor_trend", queue=QUEUE_NOTIFY)
def report_weekly_threat_actor_trend(self: Any, as_of: str | None = None) -> dict[str, object]:
    """Top 5 threat actor pekan ini vs pekan lalu -> topik `top_ta`. `as_of` (ISO 8601, naif =
    UTC) mengulang laporan yang terlewat untuk jendela yang berakhir di waktu itu."""
    end = datetime.datetime.fromisoformat(as_of) if as_of else datetime.datetime.now(datetime.UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=datetime.UTC)
    with sync_session() as session:
        report = threat_actor_trend.collect(session, end)
    if report is None:
        log.info("threat_actor_trend_empty", as_of=end.isoformat())
        return {"status": "empty"}

    send_alert("top_ta", report.message())
    return {"status": "sent", "actors": len(report.rows)}
