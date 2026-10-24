"""Port dari `ScraperNewsWeb/app/routers/ransomware.py`. Baca doang --
tabel `ransomware_victims` cuma ditulis scraper (lihat docstring model)."""

from __future__ import annotations

import datetime

from cti_core.db.models.ransomware import RansomwareVictim
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.ransomware import AsyncRansomwareVictimRepo
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import get_db, require_auth, require_permission
from cti_api.routers.articles import _serialize as _serialize_article
from cti_api.schemas.article import ArticleOut
from cti_api.schemas.ransomware import RansomwareVictimOut

router = APIRouter(
    prefix="/api/ransomware",
    tags=["ransomware"],
    dependencies=[Depends(require_permission("view_intel")), Depends(require_auth)],
)


def _serialize(v: RansomwareVictim) -> RansomwareVictimOut:
    return RansomwareVictimOut(
        id=v.id,
        group_name=v.group_name,
        victim=v.victim,
        domain=v.domain,
        description=v.description,
        country_code=v.country_code,
        industry=v.industry,
        published=v.published.isoformat() if v.published else None,
        discovered=v.discovered.isoformat() if v.discovered else None,
        post_url=v.post_url,
        ransom=v.ransom,
        data_size=v.data_size,
        screenshot=v.screenshot,
    )


@router.get("/victims")
async def list_victims(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    group: str | None = None,
    country: str | None = None,
    industry: str | None = None,
    date_start: datetime.date | None = None,
    date_end: datetime.date | None = None,
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    victims, total = await AsyncRansomwareVictimRepo(session).list_filtered(
        page=page,
        page_size=page_size,
        group=group,
        country=country,
        industry=industry,
        date_start=date_start,
        date_end=date_end,
    )
    return {
        "victims": [_serialize(v) for v in victims],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/victims/filters")
async def victim_filters(session: AsyncSession = Depends(get_db)) -> dict[str, list[str]]:
    return await AsyncRansomwareVictimRepo(session).get_filter_options()


@router.get("/related-articles")
async def related_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    article_repo = AsyncArticleRepo(session)
    articles, total = await AsyncRansomwareVictimRepo(session).get_related_articles(
        page=page, page_size=page_size
    )
    serialized: list[ArticleOut] = [
        _serialize_article(a, article_repo.to_dict(a)) for a in articles
    ]
    return {"articles": serialized, "total": total, "page": page, "page_size": page_size}
