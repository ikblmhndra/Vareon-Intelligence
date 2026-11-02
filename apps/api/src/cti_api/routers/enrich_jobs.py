"""Antrean kerja LLM yang tahan banting (`enrich_jobs`, P7g): daftar, keputusan analis, coba ulang.

Baca memakai permission yang sama dengan `/api/filtered-articles` (`view_news`). `accept`/`reject`
(`manage_sources`) menggantikan vonis LLM untuk job `classify` lewat `enrich.llm(decision=...)`;
`retry` (`manage_scraper`) mengembalikan job `failed` ke `pending` dan dispatcher yang mengirimnya.
"""

from __future__ import annotations

import datetime
from typing import Literal

from cti_core.celery_client import send_enrich_llm
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.enrich_job import AsyncEnrichJobRepo
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, get_db, request_ip, require_auth, require_permission
from cti_api.schemas.enrich_job import EnrichJobListResponse, EnrichJobOut

router = APIRouter(
    prefix="/api/enrich-jobs",
    tags=["enrich-jobs"],
    dependencies=[Depends(require_permission("view_news")), Depends(require_auth)],
)


def _p_threat_news(job: EnrichJob) -> float | None:
    relevance = job.context.get("relevance")
    probs = relevance.get("probs") if isinstance(relevance, dict) else None
    value = probs.get("threat_news") if isinstance(probs, dict) else None
    return float(value) if isinstance(value, int | float) else None


def _serialize(job: EnrichJob) -> EnrichJobOut:
    return EnrichJobOut(
        id=job.id,
        kind=job.kind,  # type: ignore[arg-type]
        url=job.url,
        title=job.title,
        source=job.source,
        posted_on=job.posted_on.isoformat() if job.posted_on else None,
        state=job.state,  # type: ignore[arg-type]
        attempts=job.attempts,
        last_error=job.last_error,
        created_at=job.created_at.isoformat(),
        next_attempt_at=job.next_attempt_at.isoformat(),
        p_threat_news=_p_threat_news(job),
    )


@router.get("", response_model=EnrichJobListResponse)
async def list_jobs(
    kind: Literal["classify", "ttp"] | None = None,
    state: Literal["pending", "failed"] | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
) -> EnrichJobListResponse:
    rows, total = await AsyncEnrichJobRepo(session).list(
        kind=kind, state=state, search=search, page=page, page_size=page_size
    )
    return EnrichJobListResponse(
        items=[_serialize(r) for r in rows], total=total, page=page, page_size=page_size
    )


async def _decide(
    job_id: int,
    decision: Literal["accept", "reject"],
    request: Request,
    session: AsyncSession,
    user: AuthedUser,
) -> dict[str, bool]:
    job = await AsyncEnrichJobRepo(session).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.kind != "classify":
        raise HTTPException(status_code=409, detail="Only classify jobs take an analyst decision")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action=f"enrich_job_{decision}",
        target_id=str(job.id),
        detail={"url": job.url, "title": job.title, "state": job.state},
        ip_address=request_ip(request),
    )
    await session.commit()
    # Kirim sesudah commit: audit sudah tersimpan, dan task membaca job dari DB.
    send_enrich_llm(job_id, decision)
    return {"success": True}


@router.post("/{job_id}/accept", dependencies=[Depends(require_permission("manage_sources"))])
async def accept_job(
    job_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    return await _decide(job_id, "accept", request, session, user)


@router.post("/{job_id}/reject", dependencies=[Depends(require_permission("manage_sources"))])
async def reject_job(
    job_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    return await _decide(job_id, "reject", request, session, user)


@router.post("/{job_id}/retry", dependencies=[Depends(require_permission("manage_scraper"))])
async def retry_job(
    job_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    """`failed` -> `pending`, jatuh tempo sekarang, `json_failures=0`; dispatcher yang mengirim."""
    repo = AsyncEnrichJobRepo(session)
    job = await repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.state != "failed":
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried")
    await repo.retry(job, datetime.datetime.now(datetime.UTC))
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="enrich_job_retry",
        target_id=str(job.id),
        detail={"url": job.url, "kind": job.kind},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"success": True}
