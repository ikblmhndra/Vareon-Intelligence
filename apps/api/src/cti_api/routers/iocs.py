"""Port dari `ScraperNewsWeb/app/routers/iocs.py`. `ioc_id` sekarang `int`
(Postgres bigint), bukan Mongo ObjectId hex string -- penyesuaian yang
emang udah kejadian pas migrasi skema (sama pola kayak `articles.py`).

`upsert_ioc`/`persist_iocs_from_extraction` (`ioc_service.py` lama) SENGAJA
gak diport -- itu jalur TULIS lama yang udah digantikan `IOCRepo.upsert()`
(Fase 5, dipanggil `cti_enrich.stages.persist` via Celery task `enrich.article`,
live-verified Fase 6). Router ini cuma permukaan BACA + kurasi manual
(tag/TA/feedback/allowlist), bukan jalur tulis IOC baru.

Fase 7.4 Grup D (2026-09-19 survei, 2026-09-23 dikerjain) nambahin `GET
/fp-analytics` + `/fp-analytics/apply-suggestions`, `GET /ta-links/{type}/
{value}`, dan ngelengkapin `/{ioc_id}/feedback` biar recompute confidence+
actionability (persis `submit_feedback()` lama) -- tiga blocker (statistik
FP, router `ta_groups`/`attack`, `confidence_service`) sekarang semua udah
resolve.

**Masih belum diport**: `decay_sweep()` (item **7.8**, Celery beat --
salah satu dari 5 loop)."""

from __future__ import annotations

import datetime
from typing import Literal

from cti_core.db.models.ioc import IOC
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.ioc_reference import AsyncIocAllowlistRepo
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    get_db,
    request_ip,
    require_auth,
    require_permission,
)
from cti_api.services import confidence, fp_analytics
from cti_api.services import ioc_ta_links as ioc_ta_links_service

router = APIRouter(
    prefix="/api/iocs", tags=["iocs"], dependencies=[Depends(require_permission("view_ioc"))]
)


class TagBody(BaseModel):
    tags: list[str]


class ThreatActorBody(BaseModel):
    threat_actors: list[str]


class FeedbackBody(BaseModel):
    verdict: Literal["tp", "fp"]
    note: str | None = None


class BulkDeleteBody(BaseModel):
    ids: list[int]


class AllowlistBody(BaseModel):
    type: Literal["url_domain", "email_domain", "ip"]
    value: str


def _serialize_summary(ioc: IOC) -> dict[str, object]:
    return {
        "id": ioc.id,
        "type": ioc.type,
        "value": ioc.value,
        "first_seen": ioc.first_seen_at.isoformat(),
        "last_seen": ioc.last_seen_at.isoformat(),
        "seen_count": ioc.seen_count,
        "tags": [t.tag for t in ioc.tags],
        "threat_actors": [t.threat_actor for t in ioc.threat_actors],
        "tp_count": ioc.tp_count,
        "fp_count": ioc.fp_count,
        "confidence_score": ioc.confidence_score,
        "actionability_score": ioc.actionability_score,
        "actionability_label": ioc.actionability_label,
        "recommended_action": ioc.recommended_action,
        "auto_suppressed": ioc.auto_suppressed,
        "suppression_reason": ioc.suppression_reason,
    }


def _serialize_detail(ioc: IOC) -> dict[str, object]:
    return {
        **_serialize_summary(ioc),
        "enrichment": ioc.enrichment or None,
        "sources": [
            {
                "url": s.url,
                "source_name": s.source_name,
                "context": s.context,
                "article_id": s.article_id,
                "first_seen": s.first_seen_at.isoformat(),
            }
            for s in ioc.sources
        ],
    }


@router.get("")
async def list_iocs(
    ioc_type: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = None,
    actionability: str | None = None,
    include_suppressed: bool = False,
    session: AsyncSession = Depends(get_db),
    _user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    iocs, total = await AsyncIOCRepo(session).list_filtered(
        page=page,
        page_size=page_size,
        ioc_type=ioc_type,
        search=search,
        sort_by=sort_by,
        actionability=actionability,
        include_suppressed=include_suppressed,
    )
    return {
        "iocs": [_serialize_summary(i) for i in iocs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/stats")
async def ioc_stats(
    session: AsyncSession = Depends(get_db), _user: AuthedUser = Depends(require_auth)
) -> dict[str, object]:
    return await AsyncIOCRepo(session).get_stats()


@router.get("/fp-analytics")
async def ioc_fp_analytics(
    force: bool = Query(False),
    session: AsyncSession = Depends(get_db),
    _user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    return await fp_analytics.get_fp_analytics(session, force=force)


@router.post("/fp-analytics/apply-suggestions")
async def apply_fp_suggestions(
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_permission("manage_ioc")),
) -> dict[str, int]:
    analytics = await fp_analytics.get_fp_analytics(session)
    suggestions = analytics.get("suggested_allowlist", [])
    allowlist_repo = AsyncIocAllowlistRepo(session)
    added = 0
    skipped = 0
    for s in suggestions:
        al_type = s.get("allowlist_type")
        value = s.get("value", "")
        if not al_type or not value:
            continue
        if al_type == "email_domain" and "@" in value:
            value = value.split("@")[-1]
        try:
            await allowlist_repo.create(entry_type=al_type, value=value, added_by=user["username"])
            added += 1
        except ValueError:
            skipped += 1
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="apply_fp_suggestions",
        detail={"added": added, "skipped": skipped},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"added": added, "skipped": skipped}


@router.get("/allowlist")
async def ioc_allowlist_list(
    session: AsyncSession = Depends(get_db), _user: AuthedUser = Depends(require_auth)
) -> dict[str, object]:
    entries = await AsyncIocAllowlistRepo(session).list_all()
    return {
        "entries": [
            {
                "id": e.id,
                "type": e.type,
                "value": e.value,
                "note": e.note,
                "added_by": e.added_by,
                "added_at": e.created_at.isoformat(),
            }
            for e in entries
        ]
    }


@router.post("/allowlist")
async def ioc_allowlist_add(
    body: AllowlistBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_permission("manage_ioc")),
) -> dict[str, object]:
    repo = AsyncIocAllowlistRepo(session)
    try:
        entry = await repo.create(entry_type=body.type, value=body.value, added_by=user["username"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="add_ioc_allowlist",
        target_id=f"{body.type}:{body.value}",
        ip_address=request_ip(request),
    )
    await session.commit()
    return {
        "id": entry.id,
        "type": entry.type,
        "value": entry.value,
        "added_by": entry.added_by,
        "added_at": entry.created_at.isoformat(),
    }


@router.delete("/allowlist/{entry_id}")
async def ioc_allowlist_remove(
    entry_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_permission("manage_ioc")),
) -> dict[str, bool]:
    ok = await AsyncIocAllowlistRepo(session).delete(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Allowlist entry not found")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="remove_ioc_allowlist",
        target_id=str(entry_id),
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True}


@router.post(
    "/{ioc_type}/{value:path}/threat-actors",
    dependencies=[Depends(require_permission("manage_ioc"))],
)
async def add_ioc_threat_actors(
    ioc_type: str,
    value: str,
    body: ThreatActorBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    repo = AsyncIOCRepo(session)
    ioc = await repo.get(type=ioc_type, value=value)
    if ioc is None:
        raise HTTPException(status_code=404, detail="IOC not found")
    await repo.add_threat_actors(ioc, body.threat_actors)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="tag_ioc_ta",
        target_id=f"{ioc_type}/{value}",
        detail={"threat_actors": body.threat_actors},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True}


@router.delete(
    "/{ioc_type}/{value:path}/threat-actors/{actor}",
    dependencies=[Depends(require_permission("manage_ioc"))],
)
async def remove_ioc_threat_actor(
    ioc_type: str,
    value: str,
    actor: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    repo = AsyncIOCRepo(session)
    ioc = await repo.get(type=ioc_type, value=value)
    if ioc is None:
        raise HTTPException(status_code=404, detail="IOC not found")
    ok = await repo.remove_threat_actor(ioc, actor)
    if not ok:
        raise HTTPException(status_code=404, detail="IOC not found")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="untag_ioc_ta",
        target_id=f"{ioc_type}/{value}",
        detail={"actor": actor},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True}


@router.post("/bulk-delete")
async def bulk_delete(
    body: BulkDeleteBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_permission("manage_ioc")),
) -> dict[str, int]:
    if not body.ids:
        raise HTTPException(status_code=400, detail="ids required")
    count = await AsyncIOCRepo(session).bulk_delete(body.ids)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="bulk_delete_iocs",
        detail={"count": count},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"deleted": count}


@router.delete("/{ioc_id}")
async def delete_ioc_by_id(
    ioc_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_permission("manage_ioc")),
) -> dict[str, bool]:
    ok = await AsyncIOCRepo(session).delete(ioc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="IOC not found")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="delete_ioc",
        target_id=str(ioc_id),
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True}


@router.post("/{ioc_id}/feedback")
async def ioc_feedback(
    ioc_id: int,
    body: FeedbackBody,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    """Port `submit_feedback()` -- feedback + recompute confidence+
    actionability + peringatan FP-rate sumber, SATU alur (Fase 7.4 Grup D
    ngelengkapin ini; sebelumnya cuma `add_feedback()` doang)."""
    repo = AsyncIOCRepo(session)
    ioc = await repo.get_by_id(ioc_id)
    if ioc is None:
        raise HTTPException(status_code=404, detail="IOC not found")
    ioc = await repo.add_feedback(
        ioc, verdict=body.verdict, submitted_by=user["username"], note=body.note
    )
    now = datetime.datetime.now(datetime.UTC)
    ioc = await confidence.recompute_ioc_confidence_and_actionability(session, ioc, now=now)

    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="ioc_feedback",
        target_id=str(ioc_id),
        detail={"verdict": body.verdict, "note": body.note or ""},
    )

    fp_analytics.invalidate_fp_cache()
    result = _serialize_detail(ioc)
    if body.verdict == "fp":
        analytics = await fp_analytics.get_fp_analytics(session, force=True)
        for src in ioc.sources:
            sr = analytics.get("fp_by_source", {}).get(src.source_name)
            if sr and sr["total_iocs"] >= 5 and sr["fp_rate"] > 0.5:
                result["source_fp_warning"] = {
                    "source_name": src.source_name,
                    "fp_rate": sr["fp_rate"],
                    "fp_count": sr["fp_count"],
                    "total_iocs": sr["total_iocs"],
                }
                break

    await session.commit()
    return result


@router.get("/ta-links/{ioc_type}/{value:path}")
async def ioc_ta_links(
    ioc_type: str,
    value: str,
    session: AsyncSession = Depends(get_db),
    _user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    result = await ioc_ta_links_service.get_ioc_ta_links(session, ioc_type, value)
    if result is None:
        raise HTTPException(status_code=404, detail="IOC not found")
    return result


@router.get("/{ioc_type}/{value:path}")
async def ioc_detail(
    ioc_type: str,
    value: str,
    session: AsyncSession = Depends(get_db),
    _user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    ioc = await AsyncIOCRepo(session).get(type=ioc_type, value=value)
    if ioc is None:
        raise HTTPException(status_code=404, detail="IOC not found")
    return _serialize_detail(ioc)


@router.post(
    "/{ioc_type}/{value:path}/tags", dependencies=[Depends(require_permission("manage_ioc"))]
)
async def add_ioc_tags(
    ioc_type: str,
    value: str,
    body: TagBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    repo = AsyncIOCRepo(session)
    ioc = await repo.get(type=ioc_type, value=value)
    if ioc is None:
        raise HTTPException(status_code=404, detail="IOC not found")
    await repo.add_tags(ioc, body.tags)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="tag_ioc",
        target_id=f"{ioc_type}/{value}",
        detail={"tags": body.tags},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True}
