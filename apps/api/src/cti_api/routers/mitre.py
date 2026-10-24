"""Port dari `ScraperNewsWeb/app/routers/mitre.py`. SELURUH router ini
`require_auth` (deklarasi level-router), sama kayak `attack.py` -- gak
ada asimetri baca-vs-tulis di sini."""

from __future__ import annotations

from cti_core.db.models.article import Article
from cti_core.db.repositories.mitre import AsyncMitreHeatmapRepo
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import get_db, require_auth, require_permission
from cti_api.services.d3fend import get_d3fend_countermeasures

router = APIRouter(
    prefix="/api/mitre",
    tags=["mitre"],
    dependencies=[Depends(require_permission("view_intel")), Depends(require_auth)],
)


def _article_out(a: Article) -> dict[str, object]:
    return {
        "_id": str(a.id),
        "title": a.title,
        "url": a.url,
        "posted_on": a.posted_on.isoformat() if a.posted_on else None,
        "source": a.source,
        "news_type": a.news_type,
    }


@router.get("/heatmap")
async def mitre_heatmap(
    view: str = Query("ta", pattern="^(ta|industry)$"),
    days: int = Query(90, ge=7, le=365),
    top_rows: int = Query(15, ge=3, le=30),
    top_ttps: int = Query(20, ge=5, le=40),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await AsyncMitreHeatmapRepo(session).get_heatmap(
        view=view, days=days, top_rows=top_rows, top_ttps=top_ttps
    )


@router.get("/d3fend/{technique_id}")
async def d3fend_countermeasures(technique_id: str) -> dict[str, object]:
    return {
        "technique_id": technique_id,
        "countermeasures": await get_d3fend_countermeasures(technique_id),
    }


@router.get("/navigator-layer")
async def navigator_layer(
    view: str = Query("ta", pattern="^(ta|industry)$"),
    days: int = Query(90, ge=7, le=365),
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    layer = await AsyncMitreHeatmapRepo(session).get_navigator_layer(view=view, days=days)
    return JSONResponse(content=layer)


@router.get("/navigator-export")
async def navigator_export(
    view: str = Query("ta", pattern="^(ta|industry)$"),
    days: int = Query(90, ge=7, le=365),
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    layer = await AsyncMitreHeatmapRepo(session).get_navigator_layer(view=view, days=days)
    filename = f"cti_navigator_{view}_{days}d.json"
    return JSONResponse(
        content=layer, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/articles")
async def mitre_ttp_articles(
    ttp_id: str,
    row: str,
    view: str = Query("ta", pattern="^(ta|industry)$"),
    days: int = Query(90, ge=7, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    docs, total = await AsyncMitreHeatmapRepo(session).get_ttp_articles(
        ttp_id=ttp_id, row=row, view=view, days=days, page=page, page_size=page_size
    )
    return {
        "articles": [_article_out(a) for a in docs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
