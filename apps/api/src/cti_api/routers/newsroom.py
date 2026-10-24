"""Endpoint newsroom: topik yang sedang naik (actor/TTP) beserta negara teratas dan artikel
terbaru per topik, supaya kartu topik bisa langsung tautan ke artikelnya."""

from __future__ import annotations

import datetime

from cti_core.db.models.article import (
    Article,
    ArticleCountry,
    ArticleThreatActor,
    ArticleTTP,
)
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import get_db, require_auth
from cti_api.schemas.newsroom import TopicArticle, TopicOut, TopicsResponse
from cti_api.services import trending

router = APIRouter(prefix="/api/newsroom", tags=["newsroom"], dependencies=[Depends(require_auth)])

_TOP_COUNTRIES = 3
_MAX_WINDOW_DAYS = 3650


async def _topic_details(
    session: AsyncSession,
    item: dict[str, object],
    *,
    start: datetime.date,
    countries: list[str] | None,
    news_types: list[str] | None,
    search: str | None,
    confirmed_only: bool,
) -> tuple[list[str], TopicArticle | None]:
    """Negara teratas + artikel terbaru untuk satu topik di dalam window. Filter yang sama
    dengan perhitungan tren, supaya angka kartu dan artikel yang ditautkan konsisten."""
    if item["kind"] == "ttp":
        ids = select(ArticleTTP.article_id).where(ArticleTTP.ttp_id == item["ttp_id"])
    else:
        ids = select(ArticleThreatActor.article_id).where(
            ArticleThreatActor.threat_actor == item["name"]
        )
    scope = [Article.id.in_(ids), Article.posted_on >= start]
    if countries:
        scope.append(
            Article.id.in_(
                select(ArticleCountry.article_id).where(ArticleCountry.country_code.in_(countries))
            )
        )
    if news_types:
        scope.append(Article.news_type.in_(news_types))
    if search:
        scope.append(Article.title.ilike(f"%{search}%"))
    if confirmed_only:
        scope.append(Article.confirmed_incident.is_(True))

    top = await session.execute(
        select(ArticleCountry.country_code)
        .join(Article, Article.id == ArticleCountry.article_id)
        .where(*scope)
        .group_by(ArticleCountry.country_code)
        .order_by(func.count(func.distinct(Article.id)).desc(), ArticleCountry.country_code)
        .limit(_TOP_COUNTRIES)
    )
    latest = (
        await session.execute(
            select(Article.id, Article.title, Article.posted_on)
            .where(*scope)
            .order_by(Article.posted_on.desc().nulls_last(), Article.id.desc())
            .limit(1)
        )
    ).first()
    return (
        [c for (c,) in top.all()],
        TopicArticle(id=latest.id, title=latest.title, posted_on=latest.posted_on)
        if latest
        else None,
    )


@router.get("/topics", response_model=TopicsResponse)
async def newsroom_topics(
    posted_on_start: datetime.date | None = None,
    posted_on_end: datetime.date | None = None,  # diterima demi kesamaan param, diabaikan
    country: list[str] | None = Query(None),
    news_type: list[str] | None = Query(None),
    search: str | None = None,
    confirmed_only: bool = Query(False),
    limit: int = Query(4, ge=1, le=10),
    session: AsyncSession = Depends(get_db),
) -> TopicsResponse:
    """Topik naik untuk newsroom. Tren selalu "N hari berakhir hari ini vs N hari sebelumnya"
    (`get_trending`), jadi tanggal filter diubah jadi jendela `days` yang berjangkar ke hari
    ini: `days = (hari ini - posted_on_start).days + 1`, di-clamp ke [1, 3650] (batas yang
    sama dengan `days` di `/api/dashboard/*`): tanpa clamp, `posted_on_start=0001-01-01`
    meledak jadi 500 (tanggal sebelum tahun 1) dan tahun 1900 mengalokasikan ratusan ribu
    bucket harian. Tanggal di masa depan -> 1. `posted_on_end` diterima tapi diabaikan.
    Tanpa `posted_on_start` dipakai aturan "semua waktu" `get_trending`
    (`days=None` -> 7 hari vs 7 hari)."""
    today = datetime.date.today()
    days = (
        min(max((today - posted_on_start).days + 1, 1), _MAX_WINDOW_DAYS)
        if posted_on_start
        else None
    )
    data = await trending.get_trending(
        session,
        days=days,
        countries=country,
        news_types=news_type,
        search=search,
        confirmed_only=confirmed_only,
        limit=limit,
    )
    start = today - datetime.timedelta(days=data["window_days"] - 1)
    items: list[TopicOut] = []
    for raw in data["items"]:
        top_countries, latest = await _topic_details(
            session,
            raw,
            start=start,
            countries=country,
            news_types=news_type,
            search=search,
            confirmed_only=confirmed_only,
        )
        items.append(TopicOut(**raw, top_countries=top_countries, latest_article=latest))
    return TopicsResponse(
        items=items,
        window_days=data["window_days"],
        window_label=data["window_label"],
        baseline_reliable=data["baseline_reliable"],
        generated_at=data["generated_at"],
    )
