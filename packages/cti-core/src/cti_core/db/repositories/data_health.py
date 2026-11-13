"""Query agregat untuk halaman Data health (`GET /api/data-health`, ROADMAP #24 PR-B): kegagalan
enrichment, kesegaran sumber, dan cakupan enrichment IOC. Hanya hitungan dan cap waktu, tidak
pernah isi baris (pesan error bisa memuat potongan respons vendor).

"Gagal" = job `enrich_jobs` berstatus `failed` (P7g; baris selesai dihapus, jadi semua yang
tersisa menunggu analis). IOC dianggap "enriched" kalau
punya minimal satu kartu provider yang bukan kartu `skipped` (`ioc_providers.skipped_card`: IP
non-publik dan sejenisnya, provider tidak pernah ditanya)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.db.models.article import Article, RejectedArticle
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.models.indicator import Indicator
from cti_core.db.models.scraper import ScraperRun
from cti_core.db.models.tweet import Tweet

# Kartu yang benar-benar dicek provider: `raw.skipped` kosong. Ditulis sebagai SQL mentah
# karena `jsonb_array_elements` di FROM; tanpa operator `?` (bentrok dengan bind param `text()`).
_ENRICHED_IOC = text(
    "EXISTS (SELECT 1 FROM jsonb_array_elements("
    "COALESCE(indicators.enrichment -> 'providers', '[]'::jsonb)) AS card "
    "WHERE card -> 'raw' -> 'skipped' IS NULL)"
)


@dataclass(frozen=True)
class EnrichmentFailures:
    failed_24h: int
    failed_7d: int
    pending_replay: int
    last_failure_at: datetime.datetime | None


@dataclass(frozen=True)
class IocCoverage:
    type: str
    total: int
    enriched: int


@dataclass(frozen=True)
class PipelineWindow:
    items_found: int
    items_new: int
    articles_published: int


@dataclass(frozen=True)
class PipelineTotals:
    last_24h: PipelineWindow
    last_7d: PipelineWindow


class AsyncDataHealthRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enrichment_failures(self, now: datetime.datetime) -> EnrichmentFailures:
        """Job `enrich_jobs` berstatus `failed` (menunggu analis). Tabel ini tidak punya cap waktu
        gagal, jadi jendela 24 jam / 7 hari memakai `created_at` job: "gagal dari job yang dibuat
        dalam jendela", bukan "gagal dalam jendela". `pending_replay` = semua yang `failed`."""
        at = EnrichJob.created_at
        stmt = select(
            func.count().filter(at >= now - datetime.timedelta(hours=24)),
            func.count().filter(at >= now - datetime.timedelta(days=7)),
            func.count(),
            func.max(at),
        ).where(EnrichJob.state == "failed")
        f24, f7, pending, last = (await self.session.execute(stmt)).one()
        return EnrichmentFailures(int(f24), int(f7), int(pending), last)

    async def pipeline_totals(self, now: datetime.datetime) -> PipelineTotals:
        """Item yang diambil, item baru, dan artikel terbit per jendela 24 jam / 7 hari.

        Semua status `scraper_runs` ikut dihitung (termasuk `running`): angka ini volume kerja
        pipeline, bukan keberhasilan. Dry run tidak menulis baris, jadi tidak pernah masuk.
        "Terbit" = `articles.first_seen_at` (C8; tabel `articles` tidak punya `created_at`).
        Kedua scan sengaja tanpa indeks baru: tabelnya dibatasi retensi dan 4b tanpa migrasi
        (spec 9)."""
        d1 = now - datetime.timedelta(hours=24)
        d7 = now - datetime.timedelta(days=7)
        at = ScraperRun.started_at
        runs = select(
            func.coalesce(func.sum(ScraperRun.items_found).filter(at >= d1), 0),
            func.coalesce(func.sum(ScraperRun.items_new).filter(at >= d1), 0),
            func.coalesce(func.sum(ScraperRun.items_found), 0),
            func.coalesce(func.sum(ScraperRun.items_new), 0),
        ).where(at >= d7)
        f1, n1, f7, n7 = (await self.session.execute(runs)).one()
        first = Article.first_seen_at
        arts = select(func.count().filter(first >= d1), func.count()).where(first >= d7)
        a1, a7 = (await self.session.execute(arts)).one()
        return PipelineTotals(
            PipelineWindow(int(f1), int(n1), int(a1)),
            PipelineWindow(int(f7), int(n7), int(a7)),
        )

    async def processed_since(self, since: datetime.datetime) -> int:
        """Artikel yang SELESAI diproses pipeline sejak `since`: diterima (`articles`) ditambah
        ditolak atau gagal (`rejected_articles`). Penyebut tingkat kegagalan."""
        accepted = select(func.count()).where(Article.first_seen_at >= since)
        rejected = select(func.count()).where(RejectedArticle.rejected_at >= since)
        a = (await self.session.execute(accepted)).scalar_one()
        r = (await self.session.execute(rejected)).scalar_one()
        return int(a) + int(r)

    async def newest_article_at(self) -> datetime.datetime | None:
        return (await self.session.execute(select(func.max(Article.first_seen_at)))).scalar_one()

    async def newest_tweet_at(self) -> datetime.datetime | None:
        return (await self.session.execute(select(func.max(Tweet.fetched_at)))).scalar_one()

    async def newest_ioc_at(self) -> datetime.datetime | None:
        return (await self.session.execute(select(func.max(Indicator.last_seen_at)))).scalar_one()

    async def ioc_coverage_by_type(self) -> list[IocCoverage]:
        stmt = (
            select(Indicator.type, func.count(), func.count().filter(_ENRICHED_IOC))
            .group_by(Indicator.type)
            .order_by(func.count().desc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [IocCoverage(t, int(total), int(enriched)) for t, total, enriched in rows]
