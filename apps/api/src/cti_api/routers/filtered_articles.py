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

from cti_core.db.models.article import RejectedArticle
from cti_core.db.repositories.article import AsyncArticleRepo, AsyncRejectedArticleRepo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, get_db, require_auth
from cti_api.schemas.filtered_article import RejectedArticleListResponse, RejectedArticleOut

router = APIRouter(
    prefix="/api/filtered-articles",
    tags=["filtered-articles"],
    dependencies=[Depends(require_auth)],
)


def _serialize(a: RejectedArticle) -> RejectedArticleOut:
    return RejectedArticleOut(
        id=a.id,
        title=a.title,
        url=a.url,
        source=a.source,
        posted_on=a.posted_on.isoformat() if a.posted_on else None,
        reason=a.reason,
        rejected_at=a.rejected_at.isoformat(),
    )


@router.get("", response_model=RejectedArticleListResponse)
async def list_filtered(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    session: AsyncSession = Depends(get_db),
) -> RejectedArticleListResponse:
    rows, total = await AsyncRejectedArticleRepo(session).list_filtered(
        page=page, page_size=page_size, search=search
    )
    return RejectedArticleListResponse(
        items=[_serialize(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.post("/{article_id}/restore")
async def restore_article(
    article_id: int,
    session: AsyncSession = Depends(get_db),
    _user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    repo = AsyncRejectedArticleRepo(session)
    rejected = await repo.get_by_id(article_id)
    if rejected is None:
        raise HTTPException(status_code=404, detail="Article not found or already restored")
    await repo.restore(rejected, AsyncArticleRepo(session))
    await session.commit()
    return {"success": True}
