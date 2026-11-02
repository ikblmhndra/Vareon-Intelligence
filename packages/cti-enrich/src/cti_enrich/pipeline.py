"""Orkestrasi stage -- port alur kontrol `nlp_scan()` (`nlp.py:144-729`),
BUKAN logikanya sendiri (itu semua udah di `stages/*.py` + `routing.py`).

Persist-first (P7g, spec `2026-11-02-p7g-persist-first-design.md` 4.2): TIDAK ADA panggilan LLM
di modul ini. Alurnya dibelah dua fungsi yang dipakai bersama `enrich.article` dan job runner
(`cti_enrich.jobs`, task `enrich.llm`):

- `prepare`: normalisasi judul -> `_known_article` (kunci URL) -> berhenti juga kalau URL ini
  sudah punya job `classify` -> `fetch_text` -> `resolve_story` (P3) -> relevansi TANPA LLM:
  Tier 0 (`default_relevance="always"`), warisan story, atau gate relevansi `gated` (P5).
  `Prepared.classify_result` = `None` kalau vonisnya butuh LLM classify.
- `complete`: `summarize -> extract_iocs -> tier1 -> [score + routing, DI-SKIP kalau
  security_tech_best_practice] -> persist (atau persist_rejected) -> commit -> alert`. Kalau LLM
  TTP berlaku (bukan Tier 0, bukan warisan, bukan best practice, input TTP tidak kosong) `persist`
  menulis `llm_ttp_status='pending'` dan job `ttp` dibuat di transaksi yang sama; selain itu
  `skipped`. Alert keluar SEKARANG dengan TTP Tier 1; TTP LLM menyusul ke DB/UI tanpa pesan
  Telegram kedua (keputusan D1).

`run_pipeline` (task `enrich.article`) = `prepare`, lalu `complete` kalau relevansinya sudah
diketahui; selain itu job `classify` (teks hasil fetch + `Prepared.to_context()`) ditulis dan
di-commit. Keputusan gate `shadow`/`audit`/`llm` juga jadi job `classify`: vonis LLM-nya tetap
dibutuhkan (label P5), hanya datangnya belakangan. Gateway LLM yang mati berarti "field datang
belakangan", bukan artikel diparkir di `rejected_articles` sampai ada yang me-replay.

Tier 1 (P4, `stages/tier1.py`) = ekstraktor deterministik tanpa LLM di atas `text or summary`:
aktor/malware, teknik ATT&CK (`explicit`/`keyword`), industri, vonis insiden. Hasilnya DIGABUNG
dengan LLM (`tier1/merge.py`), tidak menggantikannya; keyword TIDAK dikirim ke LLM TTP supaya dua
sumber tetap independen untuk pengukuran. Penggabungan dengan TTP LLM sekarang terjadi di job
`ttp`; di `complete` hanya teknik Tier 1. Tier 0 dan follow-up story (tanpa LLM TTP) tetap
menjalankan Tier 1; cabang best practice hanya entitas + industri. Gagal = hasil kosong.

Dedup story (P3, `STORY__ENABLED=true`, spec 4.1): CVE kunci diambil dari judul + isi, jadi fetch
selalu di depan; fetch yang gagal memberi teks kosong, jadi CVE dari judul saja. Follow-up story
yang sudah punya `classify` mewarisinya: LLM classify DAN TTP dilewati (TTP tetap milik lead,
tidak disalin). Lead yang masih menunggu job `classify` membiarkan `stories.classify` kosong, jadi
follow-up-nya ikut menunggu; job runner memeriksa ulang story sebelum memanggil LLM. Resolve
memakai sesi SENDIRI (`cti_enrich.story.attach`) supaya kunci story cuma dipegang sebentar.
`STORY__ENABLED=false` = tanpa tulisan story (fetch tetap di depan: job `classify` butuh teksnya).

Gate relevansi (P5, `stages/relevance.py`): model lokal memprediksi relevansi dari judul.
Keputusan `gated` (yakin berita ancaman, gate menyala, bukan sampel audit) melewati LLM classify;
vonis insiden dan korbannya lalu datang dari aturan Tier 1 (di `complete`). Hasil relevansi selalu
dicatat di `raw_enrichment["relevance"]` (lewat `context` job untuk keputusan selain `gated`).
Tier 0 dan warisan story tidak menjalankan model. Gagal apa pun = job `classify` seperti `llm`.

Dua short-circuit dipertahankan APA ADANYA dari kode lama (sekarang di `complete`):

1. `related_cyber == False` -> return lebih awal, gak ada summarize/
   enrichment PENUH yang jalan (nlp.py:280-288, port apa adanya). BEDA dari
   kode lama di satu hal (Fase 7.3, keputusan eksplisit user): sekarang
   `persist_rejected()` TETAP nyatet baris ringan ke `rejected_articles`
   sebelum return -- Fase 5 awal artikel yang ditolak diam-diam ilang
   (gak ke-log di mana pun yang bisa di-query), sekarang bisa direview/
   di-restore manual lewat router `filtered_articles.py`.
2. `security_tech_best_practice == True` -> LEWATIN LLM TTP (`llm_ttp_status='skipped'`)
   DAN `score` (gak ada NER/regex group-country matching) sama sekali, nlp.py:343-367
   `return` sebelum Phase 4-6 mulai. `extract_iocs` TETAP jalan (udah kepanggil sebelum
   percabangan ini di kode lama, line 314 vs 343).

Satu pemeriksaan BARU di depan (bukan dari kode lama): URL yang sudah jadi artikel
tidak diproses ulang (`_known_article`). Dedup scraper (`scraper_seen`) di-namespace
per `scraper_id`, jadi URL yang sama dari dua feed -- atau dari feed yang sama
sesudah TTL dedup habis -- dua-duanya sampai ke sini. Dulu tiap kedatangan
menjalankan klasifikasi + TTP lewat LLM lagi, menimpa enrichment pertama, dan
mengirim alert Telegram KEDUA; sekarang cuma `seen_count`/`last_seen_at` yang naik.
URL yang masih menunggu job `classify` juga berhenti di sini (judul lain dari feed lain tidak
membuat job kedua).

`update_cve_mention` (tracking mention CVE, `nlp.py:721-726`) DIPORT di Fase
10.E (`_track_cve_mentions`, tabel `cve_mentions`) buat laporan Top CVE mingguan.
`_trackingNews`/`_counterNews` (file `.txt` counter lokal) juga gak diport --
itu artefak operasional proses tunggal; angkanya sekarang dihitung dari DB oleh
laporan harian (`report.daily_counters`, Fase 10.E), dan `scraper_runs` (Fase 2)
udah gantiin fungsinya secara lebih baik lintas-proses."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

import structlog
from cti_core.config import get_settings
from cti_core.db.models.article import Article
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.models.report_state import SCOPE_NEWS
from cti_core.db.repositories.article import ArticleRepo
from cti_core.db.repositories.enrich_job import EnrichJobRepo
from cti_core.db.repositories.report_state import CveMentionRepo
from cti_core.urlkit import url_hash
from sqlalchemy import text
from sqlalchemy.orm import Session

from cti_enrich import routing
from cti_enrich.stages import extract_iocs as extract_iocs_stage
from cti_enrich.stages import score as score_stage
from cti_enrich.stages.alert import build_message_base, route_alerts
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.extract_ttps import TTP_TEXT_CAP, TtpResult
from cti_enrich.stages.fetch_text import fetch_text
from cti_enrich.stages.persist import persist, persist_rejected
from cti_enrich.stages.relevance import RelevanceResult, gated_classify, run_relevance
from cti_enrich.stages.score import ScoreResult
from cti_enrich.stages.summarize import summarize
from cti_enrich.stages.tier1 import run_tier1
from cti_enrich.stages.title import normalize_title
from cti_enrich.story.attach import StoryLink, classify_from_story, resolve_story
from cti_enrich.tier1.merge import merge_industries, merge_ttps

log = structlog.get_logger()


def ttp_job_input(text: str, summary: str) -> str:
    """Teks yang dikirim ke model TTP (disimpan di `enrich_jobs.input_text` job `ttp`): artikel
    (dipotong `TTP_TEXT_CAP`), atau ringkasan kalau teks kosong. `verify_evidence` HARUS memakai
    string yang sama persis, jadi job runner memakai kolom itu, bukan menghitung ulang."""
    return text[:TTP_TEXT_CAP] if text else summary


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
    kedua melihat artikelnya. Konsekuensinya transaksi sesi terbuka sejak sini sampai commit
    di akhir `complete` / sesudah job `classify` ditulis. Sejak P7g tidak ada panggilan LLM di
    dalam rentang itu (dulu classify sampai 144 detik memegang kunci ini)."""
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
    """True kalau URL ini sudah jadi artikel (hanya `seen_count`/`last_seen_at` artikel lama yang
    naik) atau sudah punya job `classify` (tidak ada yang ditulis): tanpa persist maupun alert."""
    story_id: int | None = None
    """Story tempat artikel yang diterima ini menempel (P3); `None` kalau P3 mati."""
    pending_job_id: int | None = None
    """Job `classify` yang baru dibuat `run_pipeline` (P7g): vonis relevansinya butuh LLM, jadi
    artikel belum disimpan (`accepted=False` di sini BUKAN berarti ditolak)."""


@dataclass
class Prepared:
    """Hasil `prepare`: semua yang dibutuhkan `complete` tanpa fetch, resolve story, atau model
    relevansi lagi. Untuk job `classify` disimpan di kolom job (judul, URL, sumber, `posted_on`),
    `input_text` (= `text`), dan `context` (`to_context`)."""

    title: str
    """Sudah dinormalisasi (`normalize_title`)."""
    url: str
    posted_on: datetime.date | None
    source: str
    scraper_id: str | None
    text: str
    """Teks hasil `fetch_text`; "" kalau fetch gagal (ringkasan/CVE lalu dari judul saja)."""
    story: StoryLink | None
    relevance: RelevanceResult | None
    classify_result: ClassifyResult | None
    """`None` = butuh LLM classify (job `classify`); selain itu Tier 0, warisan story, atau gate."""
    content_kind: str | None
    default_relevance: str
    tlp: str
    pap: str

    def to_context(self) -> dict[str, Any]:
        """`enrich_jobs.context`. `classify_result` tidak ikut: job `classify` justru ada karena
        vonisnya belum ada."""
        return {
            "story": self.story.to_context() if self.story is not None else None,
            "relevance": self.relevance.to_audit() if self.relevance is not None else None,
            "content_kind": self.content_kind,
            "default_relevance": self.default_relevance,
            "tlp": self.tlp,
            "pap": self.pap,
        }

    @classmethod
    def from_job(cls, job: EnrichJob) -> Prepared:
        """Kebalikan `to_context` + kolom job. Key yang tidak ada (baris migrasi, job `failed`
        dari `on_failure` dengan `context={}`) memakai bawaan `run_pipeline`. `input_text` NULL
        jadi "": pemanggil yang perlu membedakan (jalankan `prepare` dulu) memeriksa kolomnya."""
        ctx = job.context or {}
        story = ctx.get("story")
        relevance = ctx.get("relevance")
        return cls(
            title=job.title,
            url=job.url,
            posted_on=job.posted_on,
            source=job.source,
            scraper_id=job.scraper_id,
            text=job.input_text or "",
            story=StoryLink.from_context(story) if story else None,
            relevance=RelevanceResult.from_audit(relevance) if relevance else None,
            classify_result=None,
            content_kind=ctx.get("content_kind"),
            default_relevance=ctx.get("default_relevance") or "classify",
            tlp=ctx.get("tlp") or "clear",
            pap=ctx.get("pap") or "clear",
        )


def prepare(
    *,
    title: str,
    url: str,
    posted_on: datetime.date | None,
    source: str,
    scraper_id: str | None,
    session: Session,
    content_kind: str | None = None,
    default_relevance: str = "classify",
    tlp: str = "clear",
    pap: str = "clear",
) -> Prepared | PipelineOutcome:
    """Bagian depan pipeline, TANPA LLM. `PipelineOutcome(duplicate=True)` kalau URL ini sudah
    jadi artikel atau sudah punya job `classify`; selain itu `Prepared`.

    `default_relevance="always"` (dari `ScraperMeta`, dicari task worker; `cti_enrich` tidak boleh
    mengimpor `cti_scraper`) untuk sumber terstruktur (KEV, exploit, advisory): pasti relevan,
    jadi LLM classify dan TTP dilewati. Penanda lewat disimpan di audit classify.

    `tlp`/`pap` (marking bawaan sumber, dari `ScraperMeta`) diteruskan ke `persist` untuk IOC."""
    title = normalize_title(title)
    known = _known_article(session, url)
    if known is not None:
        # Hanya `articles` (dan job `classify`, di bawah) yang menghentikan pipeline. URL yang
        # pernah DITOLAK tetap diklasifikasi ulang: penilaian dari judul, dan feed lain bisa
        # memberi judul berbeda.
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
    if EnrichJobRepo(session).has_classify(url_hash(url)):
        # Review Focus 1: URL yang sama (feed lain, judul lain) selagi job classify-nya menunggu.
        # Diperiksa di bawah kunci URL yang sama, jadi dua kedatangan bersamaan tidak lolos dua-dua.
        log.info("enrich_skipped_pending_classify", url=url, source=source)
        return PipelineOutcome(accepted=False, duplicate=True)

    text = fetch_text(url)
    story_cfg = get_settings().story
    story: StoryLink | None = None
    if story_cfg.enabled:
        story = resolve_story(
            title=title,
            source=source,
            text=text,
            now=datetime.datetime.now(datetime.UTC),
            cfg=story_cfg,
        )

    relevance: RelevanceResult | None = None
    classify_result: ClassifyResult | None = None
    if default_relevance == "always":
        # Tier 0 tetap classify sintetis walau story-nya punya classify: sumber terstruktur
        # dinilai dari jenisnya, dan penanda `skipped` menjaga Tier 0 tidak mengisi story.
        classify_result = ClassifyResult(
            related_cyber=True,
            reason=f"structured source: {content_kind}",
            audit={"skipped": "default_relevance=always", "content_kind": content_kind},
        )
    elif story is not None and story.inherited is not None:
        classify_result = classify_from_story(
            story.inherited,
            story_id=story.story_id,
            rule=story.rule,
            lead_article_id=story.lead_article_id,
        )
    else:
        relevance = run_relevance(session, title=title, url=url, cfg=get_settings().relevance)
        if relevance is not None and relevance.decision.decision == "gated":
            classify_result = gated_classify(relevance)
    return Prepared(
        title=title,
        url=url,
        posted_on=posted_on,
        source=source,
        scraper_id=scraper_id,
        text=text,
        story=story,
        relevance=relevance,
        classify_result=classify_result,
        content_kind=content_kind,
        default_relevance=default_relevance,
        tlp=tlp,
        pap=pap,
    )


def complete(
    prepared: Prepared, classify_result: ClassifyResult, *, session: Session, alert: bool
) -> PipelineOutcome:
    """Ekor deterministik pipeline, TANPA LLM: dari vonis `classify_result` sampai persist/alert.
    Pemanggil memegang kunci URL (`_known_article` di `prepare`, atau job runner yang mengambilnya
    lagi). Jalur terima di-commit di sini sebelum alert; jalur tolak di-commit pemanggil.

    `alert=False` menyimpan artikel tanpa Telegram (mis. vonis job yang datang terlambat untuk
    berita yang sudah tidak segar)."""
    title, url, source = prepared.title, prepared.url, prepared.source
    scraper_id, posted_on, story = prepared.scraper_id, prepared.posted_on, prepared.story
    relevance, text = prepared.relevance, prepared.text
    if not classify_result.related_cyber:
        persist_rejected(
            session=session,
            url=url,
            title=title,
            source=source,
            scraper_id=scraper_id,
            posted_on=posted_on,
            classify_result=classify_result,
            relevance=relevance,
        )
        # Story-nya SENGAJA tidak dihapus walau masih kosong (Ruling 11): artikel lain bisa sudah
        # resolve ke story ini dan masih di-enrich; menghapusnya membuat insert artikel itu gagal
        # FK. Story yang tetap kosong disapu task harian sesudah `STORY__MAX_AGE_DAYS`.
        return PipelineOutcome(accepted=False, classify_result=classify_result)

    summary = summarize(text)
    ioc_data = extract_iocs_stage.extract_iocs(text or summary, url, session)
    c2_indicator = extract_iocs_stage.check_c2_hit(ioc_data, session)
    tier1 = run_tier1(
        session=session,
        title=title,
        text=text or summary,
        victim_name=classify_result.victim_name,
        techniques=not classify_result.security_tech_best_practice,
    )
    if classify_result.audit.get("skipped") == "relevance_gate" and tier1.incident is not None:
        # LLM classify dilewati: vonis insiden + korban dari aturan (`incident_source="rule"`).
        classify_result.confirmed_incident = tier1.incident.confirmed
        if tier1.incident.confirmed:
            classify_result.victim_name = tier1.incident.victim
    # Industri gabungan dipakai di SEMUA tempat (pesan alert, routing OT, persist) supaya baris
    # tersimpan dan teks Telegram tidak berbeda.
    industries = merge_industries(classify_result.industries_impacted, tier1.industries)

    industries_display = industries[0]
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
            story=story,
            tier1=tier1,
            industries=industries,
            relevance=relevance,
            tlp=prepared.tlp,
            pap=prepared.pap,
            llm_ttp_status="skipped",
        )
        session.commit()  # lihat catatan di situs kedua: alert gagal != artikel batal
        if alert:
            route_alerts(result)
        return PipelineOutcome(
            accepted=True,
            article_id=article.id,
            news_type=result.news_type,
            classify_result=classify_result,
            story_id=story.story_id if story else None,
        )

    # LLM TTP tidak pernah dipanggil di sini (P7g): kalau berlaku, job `ttp` membawa teks yang
    # PERSIS akan dikirim ke model, dan hasilnya digabung ke mention artikel belakangan. Tier 0
    # dan warisan story (TTP milik lead, tidak disalin) tidak pernah memakai LLM TTP.
    ttp_input = ttp_job_input(text, summary)
    llm_ttp = (
        prepared.default_relevance != "always"
        and "inherited_from_story" not in classify_result.audit
        and bool(ttp_input)
    )
    ttp_result = TtpResult(has_techniques=False)
    # Gabung per ID: explicit > llm > keyword (`tier1/merge.py`); di sini baru Tier 1.
    merged_ttps = merge_ttps(ttp_result, tier1.techniques)
    ttp_string = ", ".join(f"{t.ttp_name} ({t.ttp_id})" for t in merged_ttps)

    score_result = score_stage.score(title, summary, session)
    # `score` hanya melihat judul + RINGKASAN; aktor Tier 1 dari teks penuh ditambahkan di sini
    # (huruf kecil = bentuk `mentioned_group`; disimpan lewat `routing.threat_actor_names`).
    score_result.mentioned_group = list(
        dict.fromkeys([*score_result.mentioned_group, *(a.lower() for a in tier1.actors)])
    )

    # Funding line ikut nempel di msg_data (kode lama nambahinnya di Phase 4
    # scoring, SEBELUM cascade -- lihat nlp.py:429-432), bukan di
    # `build_message_base` di atas (yang dipanggil sebelum funding_keyword
    # kehitung).
    if score_result.funding_keyword:
        msg_base += f"<b>Funding Related Article</b>: True ({score_result.funding_keyword})\n"

    routing_input = routing.RoutingInput(
        msg_data_base=msg_base,
        # Daftar MENTAH LLM selalu ikut: cek OT membaca semua isinya, termasuk industri yang
        # `resolve_industries` buang di samping "General" (mis. ["General", "Energy & Utilities"]
        # -> sumber keyword, tapi penanda OT tidak boleh hilang). Sumber keyword: + hasil Tier 1.
        industries_impacted=(
            classify_result.industries_impacted
            if industries[1] == "llm"
            else list(dict.fromkeys([*classify_result.industries_impacted, *industries[0]]))
        ),
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
        story=story,
        tier1=tier1,
        merged_ttps=merged_ttps,
        industries=industries,
        relevance=relevance,
        tlp=prepared.tlp,
        pap=prepared.pap,
        llm_ttp_status="pending" if llm_ttp else "skipped",
    )
    if llm_ttp:
        # Transaksi yang sama dengan artikelnya: tidak ada artikel `pending` tanpa job.
        EnrichJobRepo(session).create(
            kind="ttp",
            url=url,
            title=title,
            source=source,
            scraper_id=scraper_id,
            posted_on=posted_on,
            input_text=ttp_input,
            context={},
            article_id=article.id,
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
        story_id=story.story_id if story else None,
    )


def run_pipeline(
    *,
    title: str,
    url: str,
    posted_on: datetime.date | None,
    source: str,
    scraper_id: str | None,
    session: Session,
    alert: bool = True,
    content_kind: str | None = None,
    default_relevance: str = "classify",
    tlp: str = "clear",
    pap: str = "clear",
) -> PipelineOutcome:
    """Jalur task `enrich.article`: `prepare`, lalu `complete` kalau relevansinya sudah diketahui
    tanpa LLM; selain itu job `classify` ditulis dan di-commit, dan hasilnya
    `PipelineOutcome(accepted=False, pending_job_id=...)`. Argumen lihat `prepare`.

    `alert=False` (replay artikel yang gagal di-enrich) menyimpan artikel tanpa mengirim
    Telegram: beritanya sudah berhari-hari, ratusan pesan sekaligus hanya menjadi noise. Untuk
    job `classify`, alert-nya diputuskan job runner dari kesegaran `posted_on`."""
    prepared = prepare(
        title=title,
        url=url,
        posted_on=posted_on,
        source=source,
        scraper_id=scraper_id,
        session=session,
        content_kind=content_kind,
        default_relevance=default_relevance,
        tlp=tlp,
        pap=pap,
    )
    if isinstance(prepared, PipelineOutcome):
        return prepared
    if prepared.classify_result is not None:
        return complete(prepared, prepared.classify_result, session=session, alert=alert)

    job = EnrichJobRepo(session).create(
        kind="classify",
        url=prepared.url,
        title=prepared.title,
        source=prepared.source,
        scraper_id=prepared.scraper_id,
        posted_on=prepared.posted_on,
        input_text=prepared.text,
        context=prepared.to_context(),
    )
    # Commit melepas kunci URL; kedatangan berikutnya untuk URL ini melihat job-nya.
    session.commit()
    if job is None:
        # Tidak terjadi selama `has_classify` diperiksa di bawah kunci URL; dijaga saja.
        return PipelineOutcome(accepted=False, duplicate=True)
    log.info("enrich_classify_deferred", url=url, job_id=job.id, source=source)
    return PipelineOutcome(accepted=False, pending_job_id=job.id)
