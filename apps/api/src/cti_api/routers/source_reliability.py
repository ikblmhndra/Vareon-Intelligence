"""Port dari `ScraperNewsWeb/app/routers/source_reliability.py` --
grading Admiralty manual analis atas nama sumber (bukan per-artikel),
global lintas client (lihat docstring `cti_core.db.repositories.
source_reliability`). `GET` endpoints (`/entries`, `/stats`, `/labels`,
`/ungraded-sources`) SENGAJA gak `require_auth` -- port apa adanya,
legacy juga gak nge-gate GET di router ini, cuma POST/PUT/DELETE yang
di-gate. Sama pola asimetri baca-vs-tulis kayak `articles.py`.

QA 2026-10-05: catatan 'tanpa require_auth' di atas SUDAH TIDAK BERLAKU -- semua endpoint router ini
sekarang wajib login (`require_auth`).
"""

from __future__ import annotations

import datetime

from cti_core.celery_client import send_recompute_source
from cti_core.confidence import suggest_grade
from cti_core.db.models.source_reliability import SourceReliabilityEntry
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.source_reliability import (
    CREDIBILITY_LABELS,
    RELIABILITY_LABELS,
    AsyncSourceReliabilityRepo,
)
from cti_core.logging import get_logger
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, get_db, request_ip, require_auth, require_permission
from cti_api.schemas.source_reliability import (
    SRConfirmIn,
    SREntryAdd,
    SREntryListResponse,
    SREntryOut,
    SREntryUpdate,
    SRReviewItem,
    SRReviewResponse,
)

log = get_logger()

router = APIRouter(
    prefix="/api/sr",
    tags=["source-reliability"],
    dependencies=[Depends(require_permission("view_intel")), Depends(require_auth)],
)

REVIEW_WINDOW_DAYS = 30
"""Jendela statistik antrean review grade sumber (P6 spec 5.3)."""


def _enqueue_recompute(source_name: str) -> None:
    """Skor artikel sumber ini dihitung ulang di worker (maintenance). Gagal kirim dicatat saja:
    grade sudah tersimpan, recompute bisa dipicu ulang."""
    try:
        send_recompute_source(source_name)
    except Exception:
        log.warning("recompute_source_enqueue_failed", source=source_name, exc_info=True)


def _serialize(e: SourceReliabilityEntry) -> SREntryOut:
    return SREntryOut(
        id=e.id,
        source_name=e.source_name,
        analyst_name=e.analyst_name,
        reliability_grade=e.reliability_grade,
        credibility_code=e.credibility_code,
        admiralty_code=e.admiralty_code,
        notes=e.notes,
        added_date=e.added_date.isoformat(),
        last_updated=e.last_updated.isoformat(),
        origin=e.origin,  # type: ignore[arg-type]
        content_kind=e.content_kind,
    )


@router.get("/entries", response_model=SREntryListResponse)
async def list_sr_entries(
    search: str | None = None,
    grade: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = Query("source_name"),
    sort_dir: str = Query("asc"),
    session: AsyncSession = Depends(get_db),
) -> SREntryListResponse:
    entries, total = await AsyncSourceReliabilityRepo(session).list_entries(
        search=search,
        grade=grade,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return SREntryListResponse(
        entries=[_serialize(e) for e in entries], total=total, page=page, page_size=page_size
    )


@router.get("/stats")
async def sr_stats(session: AsyncSession = Depends(get_db)) -> dict[str, object]:
    return await AsyncSourceReliabilityRepo(session).get_stats()


@router.get("/labels")
async def sr_labels() -> dict[str, dict[str, str]]:
    return {"reliability": RELIABILITY_LABELS, "credibility": CREDIBILITY_LABELS}


@router.get("/ungraded-sources")
async def ungraded_sources(session: AsyncSession = Depends(get_db)) -> dict[str, list[str]]:
    sources = await AsyncSourceReliabilityRepo(session).get_ungraded_sources()
    return {"sources": sources}


@router.post("/entries", dependencies=[Depends(require_permission("manage_sources"))])
async def add_sr_entry(
    body: SREntryAdd,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    repo = AsyncSourceReliabilityRepo(session)
    entry, reason = await repo.add_entry(
        source_name=body.source_name.strip(),
        analyst_name=body.analyst_name.strip(),
        reliability_grade=body.reliability_grade.upper(),
        credibility_code=body.credibility_code,
        notes=body.notes.strip(),
    )
    if entry is None:
        return {"success": False, "reason": reason}
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="add_source_rating",
        target_id=body.source_name,
        detail={"grade": body.reliability_grade, "code": entry.credibility_code},
        ip_address=request_ip(request),
    )
    await session.commit()
    _enqueue_recompute(entry.source_name)
    return {"success": True, "entry": _serialize(entry).model_dump()}


@router.get(
    "/review",
    response_model=SRReviewResponse,
    dependencies=[Depends(require_permission("manage_sources"))],
)
async def review_sources(session: AsyncSession = Depends(get_db)) -> SRReviewResponse:
    """Antrean review: tiap baris grade bawaan (`origin='default'`) dengan statistik 30 hari dan
    saran grade dari `suggest_grade`. Baris analis tidak ikut: grade-nya sudah keputusan manusia."""
    since = datetime.date.today() - datetime.timedelta(days=REVIEW_WINDOW_DAYS)
    rows = await AsyncSourceReliabilityRepo(session).review_stats(since=since)
    items: list[SRReviewItem] = []
    for entry, stats in rows:
        suggestion = suggest_grade(entry.reliability_grade, stats)
        items.append(
            SRReviewItem(
                entry=_serialize(entry),
                articles=stats.articles,
                rejected=stats.rejected,
                artefact_articles=stats.artefact_articles,
                multi_source_stories=stats.multi_source_stories,
                lead_count=stats.lead_count,
                ioc_verdicts=stats.ioc_verdicts,
                ioc_fp=stats.ioc_fp,
                rejected_pct=stats.rejected_pct,
                artefact_pct=stats.artefact_pct,
                ioc_fp_pct=stats.ioc_fp_pct,
                suggested_grade=suggestion.grade if suggestion else None,
                suggestion_reasons=suggestion.reasons if suggestion else [],
            )
        )
    return SRReviewResponse(items=items)


@router.post(
    "/entries/{entry_id}/confirm",
    response_model=SREntryOut,
    dependencies=[Depends(require_permission("manage_sources"))],
)
async def confirm_sr_entry(
    entry_id: int,
    body: SRConfirmIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> SREntryOut:
    """Analis mengambil alih baris (origin jadi `analyst`, `analyst_name` = user login), opsional
    dengan grade baru. Recompute skor artikel hanya kalau grade benar-benar berubah."""
    entry, changed = await AsyncSourceReliabilityRepo(session).confirm(
        entry_id, analyst_name=user["username"], reliability_grade=body.reliability_grade
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="confirm_source_rating",
        target_id=entry.source_name,
        detail={"grade": entry.reliability_grade, "grade_changed": changed},
        ip_address=request_ip(request),
    )
    await session.commit()
    if changed:
        _enqueue_recompute(entry.source_name)
    return _serialize(entry)


@router.put("/entries/{entry_id}", dependencies=[Depends(require_permission("manage_sources"))])
async def update_sr_entry(
    entry_id: int,
    body: SREntryUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    repo = AsyncSourceReliabilityRepo(session)
    ok = await repo.update_entry(
        entry_id,
        analyst_name=body.analyst_name.strip(),
        reliability_grade=body.reliability_grade.upper(),
        credibility_code=body.credibility_code,
        notes=body.notes.strip(),
    )
    # Port apa adanya: legacy gak raise 404 di sini, tetep nulis audit log
    # dan balikin {"success": False} kalau entry-nya gak ada.
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="update_source_rating",
        target_id=str(entry_id),
        detail={"grade": body.reliability_grade},
        ip_address=request_ip(request),
    )
    await session.commit()
    if ok:
        updated = await repo.get_by_id(entry_id)
        if updated is not None:
            _enqueue_recompute(updated.source_name)
    return {"success": ok}


@router.delete("/entries/{entry_id}", dependencies=[Depends(require_permission("manage_sources"))])
async def delete_sr_entry(
    entry_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    ok = await AsyncSourceReliabilityRepo(session).delete_entry(entry_id)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="delete_source_rating",
        target_id=str(entry_id),
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"success": ok}
