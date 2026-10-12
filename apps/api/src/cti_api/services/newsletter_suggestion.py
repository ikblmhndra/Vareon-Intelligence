"""Saran konten newsletter dari DB (ROADMAP #22, PR 7): jembatan antara tabel dan fungsi murni
`newsletter_ranking.rank_candidates`.

Alur `build_suggestion(session, start, end)`:

1. Baca artikel jendela itu (`posted_on` di antara `start` dan `end`, inklusif), nilai yang
   dibaca = nilai EFEKTIF (override analis di `Article.overrides` menang, seperti API artikel).
2. Kumpulkan sinyal yang tidak ada di baris artikel: CVE yang disebut artikel dan statusnya di
   `cve_tracker` (KEV/PoC), ukuran kampanye (`campaign.get_recent_campaigns`), negara semua
   client, dan nama techstack aktif semua client. Newsletter ini global, jadi sinyal client
   selalu gabungan SEMUA client, bukan satu client.
3. `rank_candidates`, lalu Executive Summary dari recap mingguan (`newsletter_summary`, PR 8: satu
   panggilan LLM, atau tanpa panggilan kalau bulannya tidak punya recap), dan simpan keduanya
   sebagai satu baris `newsletter_suggestions` yang MENIMPA saran lama untuk jendela yang sama.
   Menimpa seluruh baris berarti rebuild juga membuat ulang ringkasannya (cara analis memperbaiki
   recap Senin yang telat).

Tidak ada fetch halaman ataupun penulisan selain baris saran itu; ranking-nya sendiri tanpa LLM.
Fungsi di sini tidak commit (session-first), pemanggil yang commit. Dipanggil
`POST /suggestion/rebuild` dan task terjadwal bulanan (`newsletter_schedule.prepare_monthly`).

**Dari mana CVE sebuah artikel diketahui**: tidak ada tabel artikel-CVE, tapi `persist` menulis
setiap CVE yang ia temukan di isi artikel sebagai IOC bertipe `cve` yang tersambung ke artikelnya
(`ioc_sources.article_id`), sama dengan yang dipakai `campaign.get_recent_campaigns`. Itu sumber
utama (mencakup CVE yang hanya ada di body); judul dipindai lagi dengan regex CVE newsletter
sebagai jaring pengaman untuk artikel yang IOC-nya belum ada. Status KEV/PoC hanya diketahui
untuk CVE yang di-track (tidak ada tabel KEV sendiri); CVE di luar tracker tidak memberi sinyal.
"""

from __future__ import annotations

import datetime
from typing import Any

import structlog
from cti_core.config import get_settings
from cti_core.db.models.article import Article
from cti_core.db.models.newsletter import NewsletterSuggestion
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from cti_core.db.repositories.techstack import AsyncTechStackRepo
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services import campaign as campaign_service
from cti_api.services import newsletter as newsletter_service
from cti_api.services import newsletter_edition, newsletter_summary
from cti_api.services.newsletter_ranking import Candidate, rank_candidates

log = structlog.get_logger()

PAGE_SIZE = 500
"""Artikel dibaca per halaman. Halaman dilanjutkan sampai semuanya terbaca, tanpa batas atas yang
memotong diam-diam; halaman hanya supaya satu query tidak membawa ribuan artikel beserta
relasinya sekaligus."""

CLUSTER_MIN_SIZE = 3
"""Ukuran minimum kampanye, sama dengan bagian Campaigns newsletter (`build_newsletter_context`).
Pasangan artikel kembar ditangani dedup di ranking; menurunkan angka ini membuat tiap pasangan
memicu pengayaan kampanye penuh (severity, CVE, PIR, diamond model) di `get_recent_campaigns`."""


def _now() -> datetime.datetime:
    """Satu-satunya pembaca jam di modul ini; dipatch test supaya jendela default tetap."""
    return datetime.datetime.now(datetime.UTC)


def default_window() -> tuple[datetime.date, datetime.date]:
    """Bulan kalender sebelumnya menurut zona laporan (WIB), awal dan akhir inklusif; sama dengan
    default edisi di request build newsletter (`newsletter_edition.default_period`)."""
    return newsletter_edition.default_period(_now(), get_settings().worker.report_utc_offset_hours)


async def _articles_in_window(
    session: AsyncSession, period_start: datetime.date, period_end: datetime.date
) -> list[Article]:
    repo = AsyncArticleRepo(session)
    articles: list[Article] = []
    page = 1
    while True:
        batch, total = await repo.list_filtered(
            posted_on_start=period_start,
            posted_on_end=period_end,
            page=page,
            page_size=PAGE_SIZE,
        )
        articles.extend(batch)
        if not batch or len(articles) >= total:
            return articles
        page += 1


async def _campaigns(
    session: AsyncSession, period_start: datetime.date, period_end: datetime.date
) -> list[dict[str, Any]]:
    """SATU-SATUNYA pintu ke `get_recent_campaigns`, dengan jendela `start`/`end` (PR 2): klaster
    dibangun dari artikel jendela itu saja, jadi ukuran kampanye (sinyal liputan di ranking)
    menghitung bulan yang diedisikan, bukan artikel sesudahnya sampai hari ini. Batas 2000 artikel
    terbaru di `get_recent_campaigns` berlaku: jendela yang lebih padat dikluster dari yang
    terbaru saja dan itu dicatat sebagai peringatan `campaign_article_cap_hit`."""
    return await campaign_service.get_recent_campaigns(
        session, min_size=CLUSTER_MIN_SIZE, start=period_start, end=period_end
    )


def _cluster_sizes(campaigns: list[dict[str, Any]], candidate_ids: set[int]) -> dict[int, int]:
    """`{article_id: ukuran kampanye}` hanya menghitung anggota yang kandidat (di jendela);
    kampanye yang tersisa kurang dari 2 anggota di jendela tidak memberi sinyal."""
    sizes: dict[int, int] = {}
    for campaign in campaigns:
        members = [i for i in campaign.get("member_article_ids", []) if i in candidate_ids]
        if len(members) >= 2:
            for article_id in members:
                sizes[article_id] = max(sizes.get(article_id, 1), len(members))
    return sizes


def _as_int(value: object) -> int | None:
    """Override analis bisa berbentuk apa saja; hanya angka yang dianggap nilai."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


async def load_candidates(
    session: AsyncSession, period_start: datetime.date, period_end: datetime.date
) -> list[Candidate]:
    """Artikel jendela `[period_start, period_end]` sebagai `Candidate`, sinyal DB sudah diisi."""
    articles = await _articles_in_window(session, period_start, period_end)
    if not articles:
        return []
    article_ids = [a.id for a in articles]

    iocs = await AsyncIOCRepo(session).cve_ids_by_article(article_ids)
    cves_by_article = {
        a.id: iocs.get(a.id, set()) | set(newsletter_service._extract_cve_ids(a.title, None))
        for a in articles
    }
    flags = await AsyncCveTrackerRepo(session).exploit_flags(
        sorted({cve for cves in cves_by_article.values() for cve in cves})
    )
    sizes = _cluster_sizes(await _campaigns(session, period_start, period_end), set(article_ids))

    repo = AsyncArticleRepo(session)
    candidates = []
    for article in articles:
        effective = repo.to_dict(article)
        cves = cves_by_article[article.id]
        candidates.append(
            Candidate(
                article_id=article.id,
                title=str(effective.get("title") or ""),
                source=str(effective.get("source") or ""),
                posted_on=article.posted_on,
                confidence_score=_as_int(effective.get("confidence_score")),
                confirmed_incident=bool(effective.get("confirmed_incident")),
                victim_countries=tuple(
                    sorted({c.country_code for c in article.countries if c.role == "victim"})
                ),
                mentioned_countries=tuple(
                    sorted({c.country_code for c in article.countries if c.role == "mentioned"})
                ),
                kev_cves=tuple(sorted(c for c in cves if flags.get(c, (False, False))[0])),
                poc_cves=tuple(sorted(c for c in cves if flags.get(c, (False, False))[1])),
                cluster_size=sizes.get(article.id, 1),
            )
        )
    return candidates


def _summary_log_fields(summary_text: str, summary_meta: dict[str, Any]) -> dict[str, Any]:
    """Bagian log yang sama untuk build penuh dan retry ringkasan."""
    return {
        "weeks_used": [w["week_start"] for w in summary_meta["weeks"]],
        "uncovered": summary_meta["uncovered"],
        "summary_words": len(summary_text.split()),
        "summary_skipped": bool(summary_meta["token_usage"].get("skipped")),
        "summary_error": summary_meta["error"],
        "parse_failed": summary_meta["parse_failed"],
        "token_usage": summary_meta["token_usage"],
        "model": summary_meta["model"],
        "grounding_dropped": len(summary_meta["dropped"]),
    }


async def build_suggestion(
    session: AsyncSession, period_start: datetime.date, period_end: datetime.date
) -> NewsletterSuggestion:
    """Bangun saran satu jendela (ranking + Executive Summary) dan simpan, MENIMPA saran lama
    jendela yang sama. Panggilan LLM ringkasan yang gagal TIDAK membuang rankingnya: barisnya
    tersimpan dengan `summary_text` kosong dan `summary_meta.error` terisi
    (`newsletter_summary.generate_executive_summary`). Tidak commit."""
    candidates = await load_candidates(session, period_start, period_end)
    clients = await AsyncClientRepo(session).list_all()
    ranked = rank_candidates(
        candidates,
        client_countries={c.country_code for client in clients for c in client.countries},
        monitored_techs=await AsyncTechStackRepo(session).active_names_all_clients(),
    )
    summary_text, summary_meta = await newsletter_summary.generate_executive_summary(
        session, period_start, period_end
    )
    row = await AsyncNewsletterRepo(session).upsert_suggestion(
        period_start=period_start,
        period_end=period_end,
        items=[r.to_item() for r in ranked],
        summary_text=summary_text,
        summary_meta=summary_meta,
    )
    log.info(
        "newsletter_prepared",
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        candidates=len(candidates),
        suggested=len(ranked),
        highlights=sum(1 for r in ranked if r.tier == "highlight"),
        **_summary_log_fields(summary_text, summary_meta),
    )
    return row


async def refresh_summary(session: AsyncSession, row: NewsletterSuggestion) -> NewsletterSuggestion:
    """Ulangi HANYA Executive Summary sebuah saran yang sudah ada (rankingnya tidak disentuh, begitu
    juga `created_at`): dipakai task terjadwal ketika build sebelumnya kehilangan ringkasan karena
    panggilan LLM-nya gagal. Berhasil = `error` kembali `None`. Tidak commit."""
    row.summary_text, row.summary_meta = await newsletter_summary.generate_executive_summary(
        session, row.period_start, row.period_end
    )
    await session.flush()
    log.info(
        "newsletter_summary_retried",
        period_start=row.period_start.isoformat(),
        period_end=row.period_end.isoformat(),
        **_summary_log_fields(row.summary_text, row.summary_meta),
    )
    return row
