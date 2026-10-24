"""Port `ScraperNewsWeb/app/routers/intelligence.py`. Fase 7.3 ngeport 3
endpoint portable (`spike`/`risk-matrix`/`source-scores`, baca `articles`
langsung, gak ada dependency ke cluster). Fase 7.4 Grup A (2026-09-23)
nambahin 5 endpoint sisanya -- `GET /clusters` (Pipeline 1, greedy TF-IDF
persisted, `cti_api.services.cluster`), `GET /clusters/recent` (Pipeline
2, union-find TF-IDF + enrichment kaya, `cti_api.services.campaign`),
`GET /clusters/evolution` + `GET /clusters/{id}/trends` (baca hasil
persist Pipeline 1, `cti_api.services.campaign_trend`), `GET /intelligence/
geopolitical` (terima campaign dari Pipeline 2, `cti_api.services.
geopolitical`). Lihat docstring `Cluster` model soal kenapa dua pipeline
terpisah."""

from __future__ import annotations

from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncAuditLogRepo
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
from cti_api.services import campaign as campaign_service
from cti_api.services import campaign_trend as campaign_trend_service
from cti_api.services import cluster as cluster_service
from cti_api.services import geopolitical as geopolitical_service
from cti_api.services import risk_matrix as risk_matrix_service
from cti_api.services import source_score as source_score_service
from cti_api.services import spike as spike_service

router = APIRouter(
    prefix="/api",
    tags=["intelligence"],
    dependencies=[Depends(require_permission("view_intel")), Depends(require_auth)],
)


@router.get("/spikes")
async def early_warning(
    lookback_days: int = Query(30, ge=14, le=90),
    z_threshold: float = Query(2.0, ge=1.5, le=4.0),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await spike_service.get_spikes(
        session, lookback_days=lookback_days, z_threshold=z_threshold
    )


@router.get("/intelligence/risk-matrix")
async def risk_matrix(
    days: int = Query(30, ge=7, le=90),
    compare_days: int = Query(30, ge=7, le=90),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return await risk_matrix_service.get_risk_matrix(session, days=days, compare_days=compare_days)


@router.get("/source-scores")
async def source_scores(session: AsyncSession = Depends(get_db)) -> dict[str, object]:
    options = await AsyncArticleRepo(session).get_filter_options()
    sources = sorted(s for s in options["sources"] if s)
    return {"sources": source_score_service.score_sources(sources)}


@router.get("/clusters")
async def article_clusters(
    days: int = Query(30, ge=7, le=90, description="Lookback window in days"),
    threshold: float = Query(0.35, ge=0.2, le=0.7, description="Cosine similarity threshold"),
    exclude_low_reliability: bool = Query(
        False, description="Prevent D/E/F-graded sources from anchoring new clusters"
    ),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    clusters = await cluster_service.get_clusters(
        session, days=days, threshold=threshold, exclude_low_reliability=exclude_low_reliability
    )
    return {"clusters": clusters, "total": len(clusters)}


@router.get("/clusters/recent")
async def recent_campaigns(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    min_size: int = Query(3, ge=2, le=50),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    campaigns = await campaign_service.get_recent_campaigns(
        session, days=days, client_id=cid, min_size=min_size
    )
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="view_campaigns",
        detail={"days": days, "min_size": min_size},
        ip_address=request_ip(request),
    )
    await session.commit()

    all_links = []
    seen_pairs: set[tuple[str, str]] = set()
    for c in campaigns:
        for rc in c.get("related_campaigns", []):
            pair = tuple(sorted([c["cluster_id"], rc["cluster_id"]]))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                all_links.append(
                    {
                        "source_id": c["cluster_id"],
                        "target_id": rc["cluster_id"],
                        "score": rc["link_score"],
                        "link_type": rc["link_type"],
                        "shared_elements": rc["shared_elements"],
                    }
                )
    return {"campaigns": campaigns, "campaign_links": all_links, "total": len(campaigns)}


@router.get("/clusters/evolution")
async def campaign_evolution(
    days: int = Query(30, ge=7, le=90),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    results = await campaign_trend_service.get_campaign_evolution(session, days=days)
    return {"campaigns": results, "total": len(results)}


@router.get("/clusters/{cluster_id}/trends")
async def cluster_trends(
    cluster_id: str, session: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    trend = await campaign_trend_service.get_campaign_trends(session, cluster_id)
    if not trend:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return trend


@router.get("/intelligence/geopolitical")
async def geopolitical_summary(
    days: int = Query(30, ge=7, le=90),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    campaigns = await campaign_service.get_recent_campaigns(session, days=days)
    return await geopolitical_service.get_geopolitical_summary(session, campaigns, days=days)
