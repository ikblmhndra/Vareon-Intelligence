"""Orkestrasi stage -- port alur kontrol `nlp_scan()` (`nlp.py:144-729`),
BUKAN logikanya sendiri (itu semua udah di `stages/*.py` + `routing.py`).
Urutan: `classify -> fetch_text -> summarize -> extract_iocs -> [ttp+score+
routing, DI-SKIP kalau security_tech_best_practice] -> persist -> alert`.

Dua short-circuit dipertahankan APA ADANYA dari kode lama:

1. `related_cyber == False` -> return lebih awal, gak ada fetch/summarize/
   enrichment PENUH yang jalan (nlp.py:280-288, port apa adanya). BEDA dari
   kode lama di satu hal (Fase 7.3, keputusan eksplisit user): sekarang
   `persist_rejected()` TETAP nyatet baris ringan ke `rejected_articles`
   sebelum return -- Fase 5 awal artikel yang ditolak diam-diam ilang
   (gak ke-log di mana pun yang bisa di-query), sekarang bisa direview/
   di-restore manual lewat router `filtered_articles.py`.
2. `security_tech_best_practice == True` -> LEWATIN `extract_ttps`
   (hemat 1 panggilan LLM) DAN `score` (gak ada NER/regex group-country
   matching) sama sekali, nlp.py:343-367 `return` sebelum Phase 4-6 mulai.
   `extract_iocs` TETAP jalan (udah kepanggil sebelum percabangan ini di
   kode lama, line 314 vs 343).

Satu pemeriksaan BARU di depan (bukan dari kode lama): URL yang sudah jadi artikel
tidak diproses ulang (`_known_article`). Dedup scraper (`scraper_seen`) di-namespace
per `scraper_id`, jadi URL yang sama dari dua feed -- atau dari feed yang sama
sesudah TTL dedup habis -- dua-duanya sampai ke sini. Dulu tiap kedatangan
menjalankan klasifikasi + TTP lewat LLM lagi, menimpa enrichment pertama, dan
mengirim alert Telegram KEDUA; sekarang cuma `seen_count`/`last_seen_at` yang naik.

`update_cve_mention` (tracking mention CVE, `nlp.py:721-726`) DIPORT di Fase
10.E (`_track_cve_mentions`, tabel `cve_mentions`) buat laporan Top CVE mingguan.
`_trackingNews`/`_counterNews` (file `.txt` counter lokal) juga gak diport --
itu artefak operasional proses tunggal; angkanya sekarang dihitung dari DB oleh
laporan harian (`report.daily_counters`, Fase 10.E), dan `scraper_runs` (Fase 2)
udah gantiin fungsinya secara lebih baik lintas-proses."""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass

import structlog
from cti_core.db.models.article import Article
from cti_core.db.models.report_state import SCOPE_NEWS
from cti_core.db.repositories.article import ArticleRepo
from cti_core.db.repositories.report_state import CveMentionRepo
from cti_core.db.repositories.ttp_catalog import load_catalog
from cti_core.urlkit import url_hash
from sqlalchemy import text
from sqlalchemy.orm import Session

from cti_enrich import routing
from cti_enrich.stages import extract_iocs as extract_iocs_stage
from cti_enrich.stages import score as score_stage
from cti_enrich.stages.alert import build_message_base, route_alerts
from cti_enrich.stages.classify import ClassifyResult, classify, resolve_industries
from cti_enrich.stages.extract_ttps import TtpResult, extract_ttps, normalize_ttp_result
from cti_enrich.stages.fetch_text import fetch_text
from cti_enrich.stages.persist import persist, persist_rejected
from cti_enrich.stages.score import ScoreResult
from cti_enrich.stages.summarize import summarize
from cti_enrich.stages.title import normalize_title

log = structlog.get_logger()


def _extract_ttps_or_empty(url: str, summary: str) -> TtpResult:
    """TTP itu pengayaan OPSIONAL -- klasifikasi (stage 1) UDAH nentuin artikel
    ini relevan. Kalau LLM gak ngasih JSON setelah semua percobaan
    (`extract_ttps` udah retry 3x sendiri), artikel TETAP disimpan tanpa TTP
    + dicatat di log, BUKAN dibuang. Dulu exception-nya nembus ke Celery:
    seluruh task gagal, artikel yang sudah lolos klasifikasi hilang tanpa
    jejak selain log (e2e staging Fase 10). Cuma `JSONDecodeError`: masalah
    LLM/kuota/jaringan tetap naik ke retry Celery seperti biasa."""
    if not summary:
        return TtpResult(has_techniques=False)
    try:
        return extract_ttps(summary[:2000])
    except json.JSONDecodeError as e:
        log.warning("ttp_extraction_failed_article_kept", url=url, error=str(e))
        return TtpResult(has_techniques=False)


def _track_cve_mentions(session: Session, article: Article, score_result: ScoreResult) -> None:
    """Naikkan penghitung mention CVE (`update_cve_mention`, `nlp.py:721-726`) --
    bahan laporan Top CVE mingguan. Aturan yang sengaja dijaga:

      - HANYA untuk artikel BARU (`seen_count == 1`). Kalau alert gagal dan task
        di-retry, retry-nya sekarang berhenti di `_known_article`; cek ini lapis
        kedua supaya hitungan tidak pernah dobel.
      - Sesudah `commit()` artikel dan di SAVEPOINT sendiri, dan kegagalannya cuma
        di-log: statistik gak boleh membatalkan artikel atau menahan alert.
      - Cabang `security_tech_best_practice` gak sampai sini (return lebih awal),
        sama dengan kode lama yang `return` sebelum Phase 7.
    """
    cves = [*score_result.cve_list_title, *score_result.cve_list_body]
    if not cves or article.seen_count != 1:
        return
    try:
        with session.begin_nested():
            CveMentionRepo(session).bump(
                SCOPE_NEWS, cves, on=datetime.datetime.now(datetime.UTC).date()
            )
        session.commit()
    except Exception as e:
        log.warning("cve_mention_tracking_failed", article_id=article.id, error=str(e))


_URL_LOCK_NAMESPACE = 7_311_001
"""Kunci pertama `pg_advisory_xact_lock(int4, int4)` per URL (yang kedua `hashtext(url_hash)`).
Ruang kunci dua-int TIDAK bertabrakan dengan kunci satu-bigint di tempat lain (bootstrap API,
`/auth/init`, nomor ticket, mirror CVE). Tabrakan `hashtext` antar URL berbeda hanya membuat
dua task saling menunggu sebentar, tidak salah hasil."""


def _known_article(session: Session, url: str) -> Article | None:
    """Kunci URL ini lalu cari artikelnya. Pemeriksaan "sudah ada?" saja kalah balapan:
    dua task untuk URL yang sama bisa jalan bersamaan di `worker-nlp` (concurrency > 1), dan
    artikel baru ditulis di akhir pipeline. Kunci transaksi menahan task kedua sampai task
    pertama commit (sesudah `persist`, atau di akhir jalur tolak) atau rollback, lalu task
    kedua melihat artikelnya. Konsekuensinya transaksi sesi terbuka sejak sini, selama
    panggilan LLM klasifikasi (sebelumnya baru terbuka di `extract_iocs`)."""
    h = url_hash(url)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, hashtext(:h))"), {"ns": _URL_LOCK_NAMESPACE, "h": h}
    )
    return ArticleRepo(session).get_by_url_hash(h)


@dataclass
class PipelineOutcome:
    accepted: bool
    """False kalau `related_cyber == False` -- artikel gak lanjut ke
    fetch/summarize/enrichment penuh, tapi TETAP di-log ke
    `rejected_articles` (Fase 7.3, `persist_rejected()`) buat review manual
    lewat router `filtered_articles.py` -- bukan diam-diam ilang kayak
    Fase 5 awal."""
    article_id: int | None = None
    news_type: str | None = None
    classify_result: ClassifyResult | None = None
    duplicate: bool = False
    """True kalau URL ini sudah jadi artikel: tidak ada LLM, persist, maupun alert;
    hanya `seen_count`/`last_seen_at` artikel lama yang naik."""


def run_pipeline(
    *,
    title: str,
    url: str,
    posted_on: datetime.date | None,
    source: str,
    scraper_id: str | None,
    session: Session,
    alert: bool = True,
) -> PipelineOutcome:
    """`alert=False` (replay artikel yang gagal di-enrich) menyimpan artikel tanpa mengirim
    Telegram: beritanya sudah berhari-hari, ratusan pesan sekaligus hanya menjadi noise."""
    title = normalize_title(title)
    known = _known_article(session, url)
    if known is not None:
        # Hanya `articles` yang menghentikan pipeline. URL yang pernah DITOLAK tetap
        # diklasifikasi ulang: penilaian dari judul, dan feed lain bisa memberi judul berbeda.
        ArticleRepo(session).mark_seen(known)
        log.info(
            "enrich_skipped_known_article",
            url=url,
            article_id=known.id,
            source=source,
            seen_count=known.seen_count,
        )
        return PipelineOutcome(
            accepted=True, article_id=known.id, news_type=known.news_type, duplicate=True
        )

    classify_result = classify(title)
    if not classify_result.related_cyber:
        persist_rejected(
            session=session,
            url=url,
            title=title,
            source=source,
            scraper_id=scraper_id,
            posted_on=posted_on,
            classify_result=classify_result,
        )
        return PipelineOutcome(accepted=False, classify_result=classify_result)

    text = fetch_text(url)
    summary = summarize(text)
    ioc_data = extract_iocs_stage.extract_iocs(text or summary, url, session)
    c2_indicator = extract_iocs_stage.check_c2_hit(ioc_data, session)

    industries_display = resolve_industries(classify_result.industries_impacted)
    msg_base = build_message_base(
        script_name=source,
        title=title,
        posted_on=str(posted_on or ""),
        url=url,
        industries_string=" || ".join(industries_display),
        funding_keyword=None,
    )

    if classify_result.security_tech_best_practice:
        result = routing.RoutingResult(
            news_type="Security Technology & Best Practices",
            alert_topics=["best_practice"],
            msg_data=msg_base,
        )
        article = persist(
            session=session,
            url=url,
            title=title,
            source=source,
            scraper_id=scraper_id,
            posted_on=posted_on,
            classify_result=classify_result,
            score_result=None,
            routing_result=result,
            ttp_result=None,
            ioc_data=ioc_data,
            c2_indicator=c2_indicator,
        )
        session.commit()  # lihat catatan di situs kedua: alert gagal != artikel batal
        if alert:
            route_alerts(result)
        return PipelineOutcome(
            accepted=True,
            article_id=article.id,
            news_type=result.news_type,
            classify_result=classify_result,
        )

    ttp_result = _extract_ttps_or_empty(url, summary)
    if ttp_result.techniques:
        # Normalisasi ke katalog ATT&CK SEBELUM dipakai alert/persist -- LLM
        # sering salah pasang ID/nama (QA BUG-C01), lihat `cti_core.attack_ttp`.
        ttp_result = normalize_ttp_result(ttp_result, load_catalog(session))
    ttp_string = ""
    if ttp_result.has_techniques:
        ttp_string = ", ".join(
            f"{t.technique_name} ({t.technique_id})" for t in ttp_result.techniques
        )

    score_result = score_stage.score(title, summary, session)

    # Funding line ikut nempel di msg_data (kode lama nambahinnya di Phase 4
    # scoring, SEBELUM cascade -- lihat nlp.py:429-432), bukan di
    # `build_message_base` di atas (yang dipanggil sebelum funding_keyword
    # kehitung).
    if score_result.funding_keyword:
        msg_base += f"<b>Funding Related Article</b>: True ({score_result.funding_keyword})\n"

    routing_input = routing.RoutingInput(
        msg_data_base=msg_base,
        industries_impacted=classify_result.industries_impacted,
        mentioned_group=score_result.mentioned_group,
        mentioned_countries=score_result.mentioned_countries,
        mentioned_apac_people=score_result.mentioned_apac_people,
        cve_list_title=score_result.cve_list_title,
        report_status=score_result.report_status,
        ot_status=score_result.ot_status,
        related_tech_status=score_result.related_tech_status,
        related_tech_cve_status=score_result.related_tech_cve_status,
        databreach_list=score_result.databreach_list,
        zero_day_list=score_result.zero_day_list,
        ttp_string=ttp_string,
    )
    result = routing.route(routing_input)

    article = persist(
        session=session,
        url=url,
        title=title,
        source=source,
        scraper_id=scraper_id,
        posted_on=posted_on,
        classify_result=classify_result,
        score_result=score_result,
        routing_result=result,
        ttp_result=ttp_result,
        ioc_data=ioc_data,
        c2_indicator=c2_indicator,
    )
    # COMMIT dulu sebelum alert: `persist` + `route_alerts` satu sesi/transaksi,
    # dan `sync_session()` ROLLBACK kalau ada exception. Tanpa commit ini, alert
    # Telegram yang gagal (bot mati, chat salah, jaringan) ikut MEMBATALKAN artikel
    # yang sudah ke-persist -- artikel hilang cuma karena notifikasinya gagal.
    session.commit()
    _track_cve_mentions(session, article, score_result)
    if alert:
        route_alerts(result)

    return PipelineOutcome(
        accepted=True,
        article_id=article.id,
        news_type=result.news_type,
        classify_result=classify_result,
    )
