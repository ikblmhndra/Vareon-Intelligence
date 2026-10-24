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

from cti_core.db.models.source_reliability import SourceReliabilityEntry
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.source_reliability import (
    CREDIBILITY_LABELS,
    RELIABILITY_LABELS,
    AsyncSourceReliabilityRepo,
)
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, get_db, request_ip, require_auth, require_permission
from cti_api.schemas.source_reliability import (
    SREntryAdd,
    SREntryListResponse,
    SREntryOut,
    SREntryUpdate,
)

router = APIRouter(
    prefix="/api/sr",
    tags=["source-reliability"],
    dependencies=[Depends(require_permission("view_intel")), Depends(require_auth)],
)


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
        detail={"grade": body.reliability_grade, "code": body.credibility_code},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"success": True, "entry": _serialize(entry).model_dump()}


@router.put("/entries/{entry_id}", dependencies=[Depends(require_permission("manage_sources"))])
async def update_sr_entry(
    entry_id: int,
    body: SREntryUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    ok = await AsyncSourceReliabilityRepo(session).update_entry(
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
