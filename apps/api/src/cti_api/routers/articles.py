"""Port dari `ScraperNewsWeb/app/routers/articles.py`. Fase 7.3 (Bagian 1)
ngeport permukaan BACA (list/filter/detail); Fase 7.4 Grup D (2026-09-19
survei, 2026-09-23 dikerjain) nambahin `/dashboard`, `/dedup-groups` +
param `dedup`, `/{id}/confidence`, `/confidence/recompute` -- 4 endpoint
yang tadinya ketinggalan karena blocker (normalisasi negara, dependency
scikit-learn, router `source_reliability`) yang sekarang semua udah
resolve, lihat `cti_api.services.confidence`/`dedup`/`article_dashboard`.

**Masih belum diport**: `/api/articles/backfill-iocs` (hack migrasi era
Mongo, kemungkinan besar OBSOLETE di skema baru -- `persist.py` Fase 5
udah nulis IOC lewat jalur normal, bukan backfill URL-match belakangan).
`/api/country-groups` SENGAJA di-skip -- itu peta nama->varian buat data
negara yang dulu FREE-TEXT; skema baru (`ArticleCountry.country_code`)
udah ISO alpha-2 dari enrichment, gak ada lagi varian nama yang perlu
di-grup di layer API.

QA 2026-10-05: catatan 'tanpa require_auth' di atas SUDAH TIDAK BERLAKU -- semua endpoint router ini
sekarang wajib login (`require_auth`).
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Literal

from cti_core.db.models.article import Article
from cti_core.db.models.source_reliability import SourceReliabilityEntry
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.source_reliability import AsyncSourceReliabilityRepo
from cti_core.db.repositories.story import AsyncStoryRepo
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    effective_client_id,
    get_db,
    request_ip,
    require_auth,
    require_permission,
)
from cti_api.schemas.article import (
    TTP,
    ArticleListResponse,
    ArticleOut,
    DashboardStats,
    FilterOptions,
    InferredEntity,
    MalwareRef,
    StoryRef,
)
from cti_api.schemas.dashboard_overview import (
    CveExposure,
    DashboardAttention,
    DashboardMap,
    RansomwareOverview,
    TrendingResponse,
)
from cti_api.services import (
    article_dashboard,
    confidence,
    dashboard_overview,
    inferred_ttps,
    trending,
)
from cti_api.services import dedup as dedup_service

router = APIRouter(
    prefix="/api",
    tags=["articles"],
    dependencies=[Depends(require_permission("view_news")), Depends(require_auth)],
)
"""`list_articles`/`list_filters`/`dashboard_stats`/`article_dedup_groups`
SENGAJA gak pakai `require_auth` -- port apa adanya dari legacy
(`routers/articles.py` asli juga gak ngasih dependency itu ke keempatnya,
cuma endpoint detail `{article_id}` dan tulis-confidence yang di-gate).
Asimetri ini ada di kode lama, bukan keputusan baru di sini."""


def _serialize(
    article: Article,
    machine_fields: dict[str, object],
    ratings: Mapping[str, SourceReliabilityEntry] | None = None,
    stories: Mapping[int, tuple[int, int]] | None = None,
) -> ArticleOut:
    posted_on = machine_fields.get("posted_on")
    year, month, week = 0, "", ""
    if isinstance(posted_on, datetime.date):
        iso_year, iso_week, _ = posted_on.isocalendar()
        year = posted_on.year
        month = f"{posted_on.year:04d}-{posted_on.month:02d}"
        week = f"{iso_year:04d}-W{iso_week:02d}"

    source = str(machine_fields.get("source", ""))
    rating = ratings.get(source.lower()) if ratings else None
    counts = stories.get(article.story_id) if stories and article.story_id is not None else None
    audit = article.raw_enrichment.get("classify")
    inherited = isinstance(audit, dict) and audit.get("inherited_from_story") is not None
    lead_id = audit.get("lead_article_id") if inherited and isinstance(audit, dict) else None
    return ArticleOut(
        id=article.id,
        year=year,
        month=month,
        week=week,
        title=str(machine_fields.get("title", "")),
        url=str(machine_fields.get("url", "")),
        posted_on=posted_on.isoformat() if isinstance(posted_on, datetime.date) else "",
        source=source,
        impacted_industries=[i.industry for i in article.industries],
        mentioned_countries=[c.country_code for c in article.countries if c.role == "mentioned"],
        victim_countries=[c.country_code for c in article.countries if c.role == "victim"],
        actor_countries=[c.country_code for c in article.countries if c.role == "actor"],
        threat_actors=[t.threat_actor for t in article.threat_actors],
        ttps=[
            TTP(
                id=t.ttp_id,
                name=t.ttp_name,
                source=t.source,  # type: ignore[arg-type]
                evidence=t.evidence,
            )
            for t in article.ttps
        ],
        malware=[
            MalwareRef(name=m.name, kind=m.kind)  # type: ignore[arg-type]
            for m in article.malware
        ],
        industry_source=(
            article.industries[0].source if article.industries else None  # type: ignore[arg-type]
        ),
        news_type=str(machine_fields.get("news_type") or ""),
        confidence_score=machine_fields.get("confidence_score"),  # type: ignore[arg-type]
        admiralty_code=rating.admiralty_code if rating else None,
        grade_origin=rating.origin if rating else None,  # type: ignore[arg-type]
        iocs={},
        confirmed_incident=bool(article.confirmed_incident),
        story=(
            StoryRef(id=article.story_id, article_count=counts[0], source_count=counts[1])
            if counts is not None and article.story_id is not None
            else None
        ),
        classify_inherited_from=lead_id if isinstance(lead_id, int) else None,
    )


@router.get("/articles/dedup-groups")
async def article_dedup_groups(
    days: int = Query(7, ge=1, le=30),
    threshold: float = Query(0.75, ge=0.5, le=0.99),
    limit: int = Query(500, ge=50, le=2000),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await dedup_service.get_dedup_groups(
        session, days=days, threshold=threshold, limit=limit
    )


@router.get("/articles", response_model=ArticleListResponse)
async def list_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    posted_on_start: datetime.date | None = None,
    posted_on_end: datetime.date | None = None,
    industry: list[str] | None = Query(None),
    country: list[str] | None = Query(None),
    source: list[str] | None = Query(None),
    news_type: list[str] | None = Query(None),
    threat_actor: list[str] | None = Query(None),
    search: str | None = None,
    victim_country: list[str] | None = Query(None),
    actor_country: list[str] | None = Query(None),
    title_keyword: list[str] | None = Query(None),
    ttp: list[str] | None = Query(None),
    ttp_source: list[Literal["explicit", "keyword", "llm"]] | None = Query(None),
    sort: Literal["recent", "priority"] = Query("recent"),
    confirmed_only: bool = Query(False),
    story_id: int | None = Query(None),
    dedup: bool = Query(False),
    dedup_threshold: float = Query(0.75, ge=0.5, le=0.99),
    session: AsyncSession = Depends(get_db),
) -> ArticleListResponse:
    repo = AsyncArticleRepo(session)
    articles, total = await repo.list_filtered(
        page=page,
        page_size=page_size,
        posted_on_start=posted_on_start,
        posted_on_end=posted_on_end,
        industries=industry,
        countries=country,
        victim_countries=victim_country,
        actor_countries=actor_country,
        sources=source,
        news_types=news_type,
        threat_actors=threat_actor,
        search=search,
        title_keywords=title_keyword,
        ttps=ttp,
        ttp_sources=ttp_source,
        sort=sort,
        confirmed_only=confirmed_only,
        story_id=story_id,
    )
    # Satu query rating per request (bukan per artikel) buat kode Admiralty + asal grade.
    ratings = await AsyncSourceReliabilityRepo(session).get_all_ratings()
    # Satu query story per request: (article_count, source_count) untuk story di halaman ini.
    stories = await AsyncStoryRepo(session).counts(
        sorted({a.story_id for a in articles if a.story_id is not None})
    )
    if dedup and articles:
        # `find_dedup_groups` operasi di dict, bukan ORM -- stash objek
        # `Article` aslinya balik ke tiap dict biar `_serialize()` bisa
        # dipanggil abis dedup, tanpa perlu query ulang/mapping id->article.
        machine_dicts = []
        for a in articles:
            d = dict(repo.to_dict(a))
            d["_article"] = a
            machine_dicts.append(d)
        deduped = dedup_service.find_dedup_groups(machine_dicts, dedup_threshold)
        parsed = [_serialize(d["_article"], d, ratings, stories) for d in deduped]
        return ArticleListResponse(articles=parsed, total=total, page=page, page_size=page_size)

    parsed = [_serialize(a, repo.to_dict(a), ratings, stories) for a in articles]
    return ArticleListResponse(articles=parsed, total=total, page=page, page_size=page_size)


@router.get("/filters", response_model=FilterOptions)
async def list_filters(session: AsyncSession = Depends(get_db)) -> FilterOptions:
    options = await AsyncArticleRepo(session).get_filter_options()
    return FilterOptions(**options)


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard_stats(
    posted_on_start: datetime.date | None = None,
    posted_on_end: datetime.date | None = None,
    days: int | None = Query(
        None,
        ge=1,
        le=3650,
        description="`days` hari terakhir + pembanding periode lalu; menang atas `posted_on_*`.",
    ),
    incident_only: bool = False,
    session: AsyncSession = Depends(get_db),
) -> DashboardStats:
    result = await article_dashboard.get_dashboard_stats(
        session,
        posted_on_start=posted_on_start,
        posted_on_end=posted_on_end,
        days=days,
        incident_only=incident_only,
    )
    return DashboardStats(**result)


_DaysQuery = Query(None, ge=1, le=3650, description="`days` hari terakhir; kosong = semua waktu.")


@router.get("/dashboard/map", response_model=DashboardMap)
async def dashboard_map(
    days: int | None = _DaysQuery,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> DashboardMap:
    cid = effective_client_id(user, x_client_id)
    return DashboardMap(**await dashboard_overview.get_map(session, client_id=cid, days=days))


@router.get("/dashboard/attention", response_model=DashboardAttention)
async def dashboard_attention(
    days: int | None = _DaysQuery,
    incident_only: bool = False,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> DashboardAttention:
    cid = effective_client_id(user, x_client_id)
    return DashboardAttention(
        **await dashboard_overview.get_attention(
            session, client_id=cid, days=days, incident_only=incident_only
        )
    )


@router.get("/dashboard/trending", response_model=TrendingResponse)
async def dashboard_trending(
    days: int | None = _DaysQuery, session: AsyncSession = Depends(get_db)
) -> TrendingResponse:
    return TrendingResponse(**await trending.get_trending(session, days=days))


@router.get("/dashboard/ransomware", response_model=RansomwareOverview)
async def dashboard_ransomware(
    days: int | None = _DaysQuery, session: AsyncSession = Depends(get_db)
) -> RansomwareOverview:
    return RansomwareOverview(**await dashboard_overview.get_ransomware(session, days=days))


@router.get("/dashboard/cve-exposure", response_model=CveExposure)
async def dashboard_cve_exposure(
    days: int | None = _DaysQuery,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> CveExposure:
    cid = effective_client_id(user, x_client_id)
    return CveExposure(
        **await dashboard_overview.get_cve_exposure(session, client_id=cid, days=days)
    )


@router.post(
    "/articles/{article_id}/confidence",
    dependencies=[Depends(require_permission("manage_intel")), Depends(require_auth)],
)
async def compute_article_confidence(
    article_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    score = await confidence.compute_and_store_article_confidence(session, article_id)
    if score is None:
        raise HTTPException(status_code=404, detail="Article not found")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="compute_confidence",
        target_id=str(article_id),
        detail={"score": score},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"article_id": article_id, "confidence_score": score}


@router.post(
    "/articles/confidence/recompute",
    dependencies=[Depends(require_permission("manage_intel")), Depends(require_auth)],
)
async def recompute_confidence_all(
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, int]:
    # commit per batch: recompute penuh di prod tidak memegang lock baris seluruh tabel
    result = await confidence.recompute_all_confidence(session, commit_each_batch=True)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="recompute_confidence_all",
        detail=result,
        ip_address=request_ip(request),
    )
    await session.commit()
    return result


@router.get(
    "/articles/{article_id}",
    response_model=ArticleOut,
    dependencies=[Depends(require_auth)],
)
async def get_article_by_id(article_id: int, session: AsyncSession = Depends(get_db)) -> ArticleOut:
    repo = AsyncArticleRepo(session)
    article = await repo.get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    stories = (
        await AsyncStoryRepo(session).counts([article.story_id])
        if article.story_id is not None
        else None
    )
    return _serialize(article, repo.to_dict(article), stories=stories)


@router.get(
    "/articles/{article_id}/inferred-ttps",
    response_model=list[InferredEntity],
    dependencies=[Depends(require_auth)],
)
async def get_article_inferred_ttps(
    article_id: int, session: AsyncSession = Depends(get_db)
) -> list[InferredEntity]:
    article = await AsyncArticleRepo(session).get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return await inferred_ttps.for_article(session, article)
