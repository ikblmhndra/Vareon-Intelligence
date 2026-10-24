"""Port dari `ScraperNewsWeb/app/routers/filtered_articles.py` --
"filtered" = artikel yang DITOLAK pipeline enrichment
(`classify_result.related_cyber == False`, lihat `cti_enrich.pipeline`).

Legacy baca `scraper_runs` (`accepted=False`) -- di skema Postgres itu
gantiin tabel baru `rejected_articles` (Fase 7.3, keputusan eksplisit
user buat gak diem-diemin, lihat docs/PROGRESS.md), ditulis
`cti_enrich.stages.persist.persist_rejected()`. `GET ""` SENGAJA gak
`require_auth` -- port apa adanya, legacy juga gak nge-gate endpoint ini
(cuma `POST /restore` yang di-gate), sama asimetri kayak `articles.py`.

QA 2026-10-05: catatan 'tanpa require_auth' di atas SUDAH TIDAK BERLAKU -- semua endpoint router ini
sekarang wajib login (`require_auth`).
"""

from __future__ import annotations

from typing import Literal

from cti_core.celery_client import send_enrich_task
from cti_core.db.models.article import RejectedArticle
from cti_core.db.repositories.article import AsyncArticleRepo, AsyncRejectedArticleRepo
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    get_db,
    request_ip,
    require_auth,
    require_permission,
)
from cti_api.schemas.filtered_article import RejectedArticleListResponse, RejectedArticleOut

router = APIRouter(
    prefix="/api/filtered-articles",
    tags=["filtered-articles"],
    dependencies=[Depends(require_permission("view_news")), Depends(require_auth)],
)


def _serialize(a: RejectedArticle) -> RejectedArticleOut:
    return RejectedArticleOut(
        id=a.id,
        title=a.title,
        url=a.url,
        source=a.source,
        posted_on=a.posted_on.isoformat() if a.posted_on else None,
        reason=a.reason,
        failure_kind=a.failure_kind,
        rejected_at=a.rejected_at.isoformat(),
    )


@router.get("", response_model=RejectedArticleListResponse)
async def list_filtered(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    kind: Literal["all", "unrelated", "failed"] = "all",
    session: AsyncSession = Depends(get_db),
) -> RejectedArticleListResponse:
    """`kind=unrelated`: ditolak klasifikasi LLM; `kind=failed`: enrichment GAGAL (replay)."""
    rows, total = await AsyncRejectedArticleRepo(session).list_filtered(
        page=page, page_size=page_size, search=search, kind=kind
    )
    return RejectedArticleListResponse(
        items=[_serialize(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.post("/{article_id}/restore", dependencies=[Depends(require_permission("manage_sources"))])
async def restore_article(
    article_id: int,
    session: AsyncSession = Depends(get_db),
    _user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    repo = AsyncRejectedArticleRepo(session)
    rejected = await repo.get_by_id(article_id)
    if rejected is None:
        raise HTTPException(status_code=404, detail="Article not found or already restored")
    if rejected.failure_kind is not None:
        # Restore hanya membuat artikel tanpa enrichment, dan stub itu lalu memblokir replay.
        raise HTTPException(
            status_code=409,
            detail="Enrichment failed for this article: use Replay (admin), not Restore",
        )
    await repo.restore(rejected, AsyncArticleRepo(session))
    await session.commit()
    return {"success": True}


@router.post("/{article_id}/replay")
async def replay_article(
    article_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_permission("manage_scraper")),
) -> dict[str, bool]:
    """Kirim ulang artikel yang GAGAL di-enrich ke pipeline (senyap, tanpa alert Telegram). Admin:
    memakai kuota LLM. Baris gagalnya hilang sendiri begitu artikelnya berhasil diproses."""
    repo = AsyncRejectedArticleRepo(session)
    rejected = await repo.get_by_id(article_id)
    if rejected is None:
        raise HTTPException(status_code=404, detail="Article not found")
    if rejected.failure_kind is None:
        raise HTTPException(
            status_code=409, detail="Only articles whose enrichment failed can be replayed"
        )
    if await AsyncArticleRepo(session).get_by_url(rejected.url) is not None:
        raise HTTPException(
            status_code=409,
            detail="This URL is already an article (processed or restored); nothing to replay",
        )
    send_enrich_task(
        title=rejected.title,
        url=rejected.url,
        posted_on=rejected.posted_on,
        source=rejected.source,
        scraper_id=rejected.scraper_id,
        replay=True,
    )
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="replay_enrichment",
        target_id=str(rejected.id),
        detail={"url": rejected.url, "failure_kind": rejected.failure_kind},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"success": True}
