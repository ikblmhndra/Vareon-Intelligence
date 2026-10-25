"""Registry dispatch berdasarkan TIPE item. Ini jalan keluar scraper
bespoke: `yield` tipe item yang beda, sink yang nentuin tujuannya. Gak ada
`if scraper.is_special` di mana pun di framework.

Fase 3 cuma daftarin sink buat `ArticleItem` dan `RansomwareVictimItem`.
`CveItem` dipasang Fase 4 pas beneran nge-port `newCveThreat.py` (`PackageVulnItem`
masih nunggu Fase 7, `pkg_vuln_service.py`) -- sesuai keputusan "gak bangun
lebih dulu dari kebutuhan" yang sama kayak model Fase 2.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from cti_core.config import get_settings
from cti_core.cve_promotion import NEW_CVE_ROWS_KEY
from sqlalchemy.orm import Session

from cti_scraper.errors import BackpressureError
from cti_scraper.items import (
    ArticleItem,
    CveItem,
    CveMentionItem,
    CvePocItem,
    IocFeedItem,
    Item,
    MalwareTrendItem,
    NoticeItem,
    RansomwareVictimItem,
    TweetItem,
)

if TYPE_CHECKING:
    from cti_scraper.base import ScraperMeta

# Argumen pertama `Any`, BUKAN `Item` -- tiap sink konkret nerima subclass
# spesifik (`ArticleItem`, `RansomwareVictimItem`, dst), dan `dict[type[Item],
# Sink]` di bawah dispatch pakai `type(item)` yang JAMIN kecocokan di
# runtime. Callable kontravarian bikin mypy nolak assign
# `Callable[[ArticleItem,...]]` ke slot `Callable[[Item,...]]` walau itu
# aman -- `Any` di sini jujur soal "kebenaran dijamin tabel dispatch, bukan
# signature," bukan nutupin bug.
Sink = Callable[[Any, "ScraperMeta", Session], None]

_SINKS: dict[type[Item], Sink] = {}


class NoSinkRegistered(Exception):
    """Item type di-`yield` scraper tapi belum ada yang tau cara nyimpennya."""


def sink_for(item_type: type[Item]) -> Callable[[Sink], Sink]:
    """Daftarin fungsi buat satu tipe Item. Dipanggil sebagai decorator di
    level modul (lihat contoh di bawah). Preseden yang kepake: sink
    didaftarin DI SINI (`sinks.py`), terpusat satu tempat biar dispatch
    table gampang ditemuin -- bukan di file scraper masing-masing yang
    nge-yield tipe itu (`ArticleItem`/`RansomwareVictimItem`/`CveItem`
    semuanya di sini walau scraper-nya tersebar di banyak file)."""

    def deco(fn: Sink) -> Sink:
        _SINKS[item_type] = fn
        return fn

    return deco


def dispatch(item: Item, meta: ScraperMeta, session: Session) -> None:
    sink = _SINKS.get(type(item))
    if sink is None:
        raise NoSinkRegistered(
            f"gak ada sink buat {type(item).__name__} (dari scraper '{meta.id}') "
            f"-- daftarin lewat @sink_for({type(item).__name__}) sebelum scraper "
            "yang nge-yield tipe ini dijalanin."
        )
    sink(item, meta, session)


_ENRICH_QUEUE = "enrich"
"""Sama dgn `cti_worker.queues.QUEUE_ENRICH` -- diduplikasi karena package ini
gak boleh import dari `apps/worker` (arah dependency)."""


@lru_cache(maxsize=1)
def _broker_redis() -> Any:
    import redis

    return redis.Redis.from_url(get_settings().redis.url)


def _enrich_queue_depth() -> int:
    """Panjang antrian `enrich` di broker. Celery+Redis nyimpen queue sebagai
    LIST bernama sama dgn queue-nya (gak ada priority steps di app ini), jadi
    `LLEN` langsung. Yang keitung cuma pesan yang belum diambil worker --
    yang lagi dikerjain (unacked) gak ikut, cukup buat sinyal "numpuk"."""
    return int(_broker_redis().llen(_ENRICH_QUEUE))


def enrich_queue_depth() -> int | None:
    """Versi publik `_enrich_queue_depth` buat pembaca non-sink (replay otomatis): None kalau Redis
    gak terjangkau, jadi pemanggil bisa mundur ke mode hati-hati alih-alih gagal."""
    try:
        return _enrich_queue_depth()
    except Exception:
        return None


def ensure_enrich_capacity() -> None:
    """Guard backpressure (Fase 10.1e). Scraper (~detik per run) jauh lebih
    cepat dari enrichment (~10-13 detik + LLM per artikel), jadi tanpa ini
    antrian numpuk tanpa batas -- ngabisin RAM Redis dan bikin artikel
    terkirim berjam-jam setelah kejadian. Raise `BackpressureError` kalau
    kedalaman udah >= `Settings.scraper.enrich_queue_max_depth` (`<= 0` =
    guard mati). Angka default (2000) masih tebakan awal -- disetel ulang
    begitu ada angka nyata dari `worker-nlp` produksi."""
    limit = get_settings().scraper.enrich_queue_max_depth
    if limit <= 0:
        return
    depth = _enrich_queue_depth()
    if depth >= limit:
        raise BackpressureError(f"antrian '{_ENRICH_QUEUE}' {depth} >= batas {limit}")


@sink_for(ArticleItem)
def _article_sink(item: ArticleItem, meta: ScraperMeta, session: Session) -> None:
    """Fase 6: `send_task` ke queue `enrich` (`enrich.article`, lihat
    `apps/worker/src/cti_worker/tasks/enrich.py`) -- GANTI nulis langsung
    lewat `ArticleRepo` (perilaku Fase 3). `session` di sini TETAP
    dipakai Runner buat commit/rollback dedup lease (lihat `runner.py::
    _handle_item`), tapi sink ini sendiri gak nyentuh Postgres -- cuma
    ngirim pesan Redis. `ArticleRepo.upsert()` yang beneran nulis
    `articles` sekarang jalan di task Celery terpisah (`cti_enrich.
    pipeline.run_pipeline` -> `stages/persist.py`), bukan di sini.
    Kontraknya (tipe apa yang boleh masuk sini) gak berubah dari Fase 3."""
    from cti_core.celery_client import get_celery_client

    ensure_enrich_capacity()
    get_celery_client().send_task(
        "enrich.article",
        kwargs={
            "title": item.title,
            "url": item.url,
            "posted_on": item.posted_on.isoformat() if item.posted_on else None,
            "source": meta.source,
            "scraper_id": meta.id,
        },
        queue=_ENRICH_QUEUE,
    )


@sink_for(RansomwareVictimItem)
def _ransomware_sink(item: RansomwareVictimItem, meta: ScraperMeta, session: Session) -> None:
    """Nulis langsung ke `ransomware_victims`, MELEWATI pipeline
    enrichment artikel -- inilah bukti "yield tipe beda = tujuan beda",
    bukan special-case di runner."""
    from cti_core.db.repositories.ransomware import RansomwareVictimRepo

    repo = RansomwareVictimRepo(session)
    repo.upsert(
        offset_key=item.dedup_key(),
        group_name=item.group_name,
        victim=item.victim,
        country_code=item.country_code,
        industry=item.industry,
        published=item.published,
        discovered=item.discovered,
        domain=item.domain,
        description=item.description,
        post_url=item.post_url,
        ransom=item.ransom,
        data_size=item.data_size,
        screenshot=item.screenshot,
    )


@sink_for(CveItem)
def _cve_sink(item: CveItem, meta: ScraperMeta, session: Session) -> None:
    """Upsert ke `cve_tracker`, key `(cve_id, client_id)`. `references`/
    `affected` SELALU diganti utuh, bukan di-merge -- MITRE ngasih daftar
    lengkap tiap panggilan, bukan delta (lihat `CveTrackerRepo.upsert`)."""
    from cti_core.db.repositories.cve import CveTrackerRepo

    repo = CveTrackerRepo(session)
    # `published_at` hanya ikut kalau MITRE ngasih jamnya -- jangan menimpa nilai yang sudah ada
    # (mis. hasil backfill) dengan NULL.
    extra = {"published_at": item.published_at} if item.published_at is not None else {}
    _row, created = repo.upsert_with_status(
        cve_id=item.cve_id,
        client_id=item.client_id,
        tech=item.tech,
        link=item.link,
        summary=item.summary,
        published=item.published,
        cve_modified_date=item.cve_modified_date,
        solutions=item.solutions,
        cve_score=item.cve_score,
        cve_severity=item.cve_severity,
        cvss_vector=item.cvss_vector,
        references=item.references,
        affected=item.affected,
        **extra,
    )
    if created:
        # Dikumpulkan sepanjang run, dikirim SEKALI di akhir (`finish_run`); lihat `cve_alert`.
        session.info.setdefault(_NEW_CVE_KEY, []).append((item.cve_id, item.client_id))


_NEW_CVE_KEY = NEW_CVE_ROWS_KEY
"""Kunci `Session.info`: [(cve_id, client_id)] baris `cve_tracker` yang DIBUAT run ini. Satu
definisi dengan promosi mirror (`cti_core.cve_promotion`), yang juga mengisinya."""


def finish_run(session: Session) -> None:
    """Dipanggil `Runner.execute()` SETELAH run dicatat selesai. Mengirim ringkasan CVE baru yang
    dikumpulkan `_cve_sink`. Tidak pernah raise: alert bukan alasan run gagal."""
    pairs = session.info.pop(_NEW_CVE_KEY, None)
    if pairs:
        from cti_scraper.cve_alert import notify_new_cves

        notify_new_cves(session, pairs)


@sink_for(CvePocItem)
def _cve_poc_sink(item: CvePocItem, meta: ScraperMeta, session: Session) -> None:
    """Nambahin ke `cve_tracker.pocs` -- kalau `cve_id`-nya gak ketemu di
    `cve_tracker` sama sekali (belum pernah di-track `new_cve`), POC ini
    gak punya baris buat ditempelin, `add_pocs()` no-op diam-diam. Itu
    setara perilaku `githubPOCMonitor.py` lama: fase 1-nya (broad search)
    JUGA gak nulis DB buat CVE yang gak dikenal, cuma Telegram alert
    (di luar scope scraper) -- bukan regresi baru."""
    from cti_core.db.repositories.cve import CveTrackerRepo

    repo = CveTrackerRepo(session)
    repo.add_pocs(
        cve_id=item.cve_id,
        pocs=[{"url": item.url, "source": item.source, "poc_type": item.poc_type}],
    )


@sink_for(MalwareTrendItem)
def _malware_trend_sink(item: MalwareTrendItem, meta: ScraperMeta, session: Session) -> None:
    """Upsert ke `malware_trends`, key `(source, snapshot_date, rank)` --
    posisi ranking yang sama bisa ke-upsert ulang beberapa kali dalam satu
    hari (leaderboard bisa geser antar-run), makanya `dedup_key()`
    scraper-nya di-override `None` (lihat `any_run_trends.py`) biar sink
    ini SELALU kepanggil, bukan cuma sekali per hari."""
    from cti_core.db.repositories.malware_trend import MalwareTrendRepo

    repo = MalwareTrendRepo(session)
    repo.upsert(
        source=item.source,
        snapshot_date=item.snapshot_date,
        rank=item.rank,
        malware_name=item.malware_name,
        malware_type=item.malware_type,
        url=item.url,
        report_count=item.report_count,
    )


def _format_commit_message(item: IocFeedItem, new_ioc_count: int) -> str:
    """Port bagian format `deepdarkCTI.py:108-135` (badan pesan Telegram
    darkweb) -- `files_changed[].patch_preview` udah difilter+diformat di
    `fetch()` (lihat `deepdarkCTI.py` scraper), sink cuma nyusun jadi teks."""
    msg = f"""
=== <b>DEEPDARKCTI GITHUB MONITOR</b> ===
<b>Commit Message</b>: {item.commit_message}
<b>Author</b>: {item.commit_author}
<b>Date</b>: {item.commit_date.strftime("%B %d, %Y, %H:%M:%S")}
<b>Files changed:</b>"""
    for f in item.files_changed:
        msg += f"""
    <b>Filename</b>: {f["filename"]}
    <b>Additions</b>: {f["additions"]}
    <b>Deletions</b>: {f["deletions"]}\n"""
        if f.get("patch_preview"):
            msg += f"    <b>Patch</b>: \n{f['patch_preview']}\n"
        else:
            msg += "    <b>Patch</b>: No patch available\n"
    if new_ioc_count:
        msg += f"    <b>New IOCs ingested</b>: {new_ioc_count}\n"
    return msg


@sink_for(IocFeedItem)
def _ioc_feed_sink(item: IocFeedItem, meta: ScraperMeta, session: Session) -> None:
    """Upsert tiap IOC ke `iocs` (+ `threat_feed_entries` kalau kategori
    "c2" -- gantiin `dbMongo.upsert_threat_feed`), lalu SATU alert Telegram
    topic "darkweb" -- gantiin `deepdarkCTI.py`'s inline upsert +
    `send_alert_darkweb`. Kegagalan alert (topic belum dikonfig, dst)
    TIDAK boleh gagalin IOC yang udah kesimpen -- persis prinsip Fase 5
    "persist sebelum alert" (lihat `cti_alerts.telegram` docstring)."""
    from cti_alerts.telegram import send_alert
    from cti_core.db.models.ioc_reference import ThreatFeedEntry
    from cti_core.db.repositories.ioc import IOCRepo
    from cti_core.db.repositories.ioc_reference import get_ioc_allowlist
    from cti_core.ioc.allowlist import allowlist_match
    from cti_core.ioc.canonical import canonical
    from sqlalchemy import select

    ioc_repo = IOCRepo(session)
    allowlist = get_ioc_allowlist(session)
    new_count = 0
    for entry in item.iocs:
        value = canonical(entry["type"], entry["value"])
        ioc = ioc_repo.upsert(
            type=entry["type"],
            value=value,
            source_url=item.commit_url,
            source_name="deepdarkCTI",
            context=entry["category"],
            suppression_reason=allowlist_match(entry["type"], value, allowlist),
        )
        if ioc.seen_count == 1:
            new_count += 1

        if entry["category"] == "c2" and entry["type"] in ("ip", "domain"):
            exists = session.execute(
                select(ThreatFeedEntry).where(
                    ThreatFeedEntry.feed == "deepdarkcti_c2",
                    ThreatFeedEntry.type == entry["type"],
                    ThreatFeedEntry.value == value,
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(ThreatFeedEntry(feed="deepdarkcti_c2", type=entry["type"], value=value))
                session.flush()

    # IOC udah kesimpen di atas -- gagal alert gak boleh gagalin run.
    with contextlib.suppress(Exception):
        send_alert("darkweb", _format_commit_message(item, new_count))


@sink_for(TweetItem)
def _tweet_sink(item: TweetItem, meta: ScraperMeta, session: Session) -> None:
    """Insert-only ke `tweets` -- gantiin `monitorX.py::upsert_tweet`
    (`$setOnInsert`, gak pernah update tweet yang udah ada). `source` = scraper yang nulis
    (`monitor_x` atau `tweet_alerts_*`); kalau tweet-nya udah disimpan scraper lain, ini no-op."""
    from cti_core.db.repositories.tweet import TweetRepo

    repo = TweetRepo(session)
    repo.insert(
        tweet_id=item.tweet_id,
        source=meta.id,
        url=item.url,
        text=item.text,
        author_username=item.author_username,
        author_name=item.author_name,
        author_avatar=item.author_avatar,
        author_followers=item.author_followers,
        posted_on=item.posted_on,
        lang=item.lang,
        media_urls=item.media_urls,
        scan_results=item.scan_results,
        confidence_score=item.confidence_score,
        confirmed_incident=item.confirmed_incident,
        industries_impacted=item.industries_impacted,
        victim_countries=item.victim_countries,
        actor_countries=item.actor_countries,
        victim_name=item.victim_name,
        incident_confidence=item.incident_confidence,
        incident_indicators=item.incident_indicators,
    )


@sink_for(CveMentionItem)
def _cve_mention_sink(item: CveMentionItem, meta: ScraperMeta, session: Session) -> None:
    """Naikkan `cve_mentions` (scope tweet). Idempoten lewat dedup id tweet."""
    import datetime

    from cti_core.db.models.report_state import SCOPE_TWEET
    from cti_core.db.repositories.report_state import CveMentionRepo

    CveMentionRepo(session).bump(
        SCOPE_TWEET, item.cve_ids, on=datetime.datetime.now(datetime.UTC).date()
    )


_TELEGRAM_TEXT_LIMIT = 4096


@sink_for(NoticeItem)
def _notice_sink(item: NoticeItem, meta: ScraperMeta, session: Session) -> None:
    """Kirim pesan ke Telegram. Kegagalan SENGAJA gak ditelan (beda dari
    `_ioc_feed_sink`, yang punya data lain buat diselamatkan): notice itu
    isinya SATU-SATUNYA, jadi exception -> `Runner` rollback + release dedup ->
    dicoba lagi run berikutnya. Konsekuensi: at-least-once -- kalau pengiriman
    sukses tapi commit DB sesudahnya gagal, pesan bisa terkirim dua kali;
    dipilih daripada notice hilang."""
    from cti_alerts.telegram import send_alert, send_document

    if len(item.text) > _TELEGRAM_TEXT_LIMIT:
        raise ValueError(
            f"notice '{item.key}' {len(item.text)} karakter > batas Telegram "
            f"{_TELEGRAM_TEXT_LIMIT} -- scraper harus memotong field panjangnya"
        )
    if item.attachment_text is None:
        send_alert(item.topic, item.text)
    else:
        send_document(
            item.topic, item.attachment_name or "notice.txt", item.attachment_text, item.text
        )


def reset() -> None:
    """Testing doang."""
    _SINKS.clear()
    _SINKS[ArticleItem] = _article_sink
    _SINKS[RansomwareVictimItem] = _ransomware_sink
    _SINKS[CveItem] = _cve_sink
    _SINKS[CvePocItem] = _cve_poc_sink
    _SINKS[MalwareTrendItem] = _malware_trend_sink
    _SINKS[IocFeedItem] = _ioc_feed_sink
    _SINKS[TweetItem] = _tweet_sink
    _SINKS[NoticeItem] = _notice_sink
    _SINKS[CveMentionItem] = _cve_mention_sink
