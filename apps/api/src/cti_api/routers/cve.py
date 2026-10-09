"""Port CRUD-baca + false-positive dari `ScraperNewsWeb/app/routers/cve.py`.
`POST /cisa-lookup`/`/epss-lookup`/`/exploit-lookup`/`/{id}/exploit-lookup`
(Fase 7.4 Grup B, survei 2026-09-19) SEKARANG diport -- lihat
`cti_api.services.cve_lookup`.

Fase 7.4 Grup C (2026-09-23) nambahin workflow ticket (`GET /{id}/ticket`+
`PUT`, `POST /{id}/acknowledge`+`/bulk-acknowledge`, `GET /next-ticket-id`+
`/ack-statuses`, parameter `ack_filter` di list/stats -- semua lewat
`AsyncCveTicketRepo`, skema `CveTicket` yang DIROMBAK TOTAL dari
placeholder Fase 2, lihat docstring model), `POST /draft-email`
(`cti_api.services.cve_email`), dan `GET /export` (`cti_api.services.
cve_export` -- SEKALIAN merbaiki bug lama: export gak pernah nge-scope
`client_id`, lihat docstring modul itu).

Fase 7.4 Grup A (2026-09-23) nambahin `GET /prioritize` -- ternyata
`cve_priority_service.py` (`cti_api.services.cve_priority`) BUKAN cuma
internal helper "mesin cluster" (`cti_api.services.campaign`), tapi juga
backing endpoint ad-hoc standalone ini, lihat docstring service-nya.

**Masih belum diport**: `GET /{id}/mindmap` (`mermaid_service`, generate
diagram -- SUDAH tercakup fungsional lewat `GET /api/mindmap/cve/{cve_id}`
generik, Bagian 4, endpoint spesifik lama gak perlu diduplikat)."""

from __future__ import annotations

import datetime
import io

from cti_core.db.models.cve import CveTicket, CveTracker
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.cve import (
    AsyncCveFalsePositiveRepo,
    AsyncCveTicketRepo,
    AsyncCveTrackerRepo,
)
from cti_core.db.repositories.techstack import AsyncTechStackRepo
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    effective_client_id,
    get_db,
    get_redis,
    request_ip,
    require_admin,
    require_auth,
)
from cti_api.schemas.cve import (
    AcknowledgeBody,
    BulkAcknowledgeBody,
    BulkFalsePositiveBody,
    CveId,
    CveListResponse,
    CveOut,
    CvePocOut,
    CveReferenceOut,
    CveStats,
    CveTicketBody,
    DraftEmailBody,
    PurgeOrphanedBody,
)
from cti_api.schemas.cve_check import CveCheckTriggered, CveFreshness
from cti_api.schemas.cve_dashboard import CveDashboard
from cti_api.schemas.techstack import EXPOSURE_MULTIPLIER, HOSTING_MULTIPLIER
from cti_api.services import cve_check as cve_check_service
from cti_api.services import cve_dashboard as cve_dashboard_service
from cti_api.services import cve_email as cve_email_service
from cti_api.services import cve_export as cve_export_service
from cti_api.services import cve_lookup as cve_lookup_service
from cti_api.services import cve_priority as cve_priority_service

router = APIRouter(prefix="/api/cve", tags=["cve"])

_ACK_FILTER_PATTERN = "^(acked|unacked)$"
_DATE_BASIS_PATTERN = "^(published|detected)$"


def _parse_date(value: str) -> datetime.date | None:
    return datetime.date.fromisoformat(value) if value else None


def _serialize_ticket(ticket: CveTicket | None) -> dict[str, object]:
    """Port `get_ticket()` -- `{}` kalau belum ada ticket (legacy juga
    gitu, bukan 404). `cve_reported_date` SENGAJA gak ada, lihat
    docstring `CveTicket` model -- frontend fallback ke `cve.published`
    sendiri kalau field ini gak ada di response."""
    if ticket is None:
        return {}
    return {
        "ticket_id": ticket.ticket_id,
        "cve_id": ticket.cve_id,
        "affected_asset": ticket.affected_asset or "",
        "affected_version": ticket.affected_version or "",
        "fixed_version": ticket.fixed_version or "",
        "asset_owner": ticket.asset_owner or "",
        "owner_email": ticket.owner_email or "",
        "owner_team": ticket.owner_team or "",
        "active_exploitation": ticket.active_exploitation or "",
        "remediation_date_plan": (
            ticket.remediation_date_plan.isoformat() if ticket.remediation_date_plan else ""
        ),
        "remediation_status": ticket.remediation_status or "",
        "actual_remediation_date": (
            ticket.actual_remediation_date.isoformat() if ticket.actual_remediation_date else ""
        ),
        "escalation_required": ticket.escalation_required,
        "comments": ticket.comments or "",
        "risk_acceptance": ticket.risk_acceptance or "",
        "closure_date": ticket.closure_date.isoformat() if ticket.closure_date else "",
        "acknowledged_by": ticket.acknowledged_by or "",
        "acknowledge_time": ticket.acknowledge_time.isoformat() if ticket.acknowledge_time else "",
    }


def _serialize(
    cve: CveTracker,
    *,
    is_fp: bool,
    mentions: list[dict[str, str]],
    risk_ctx: dict[str, dict[str, str]],
) -> CveOut:
    ctx = risk_ctx.get((cve.tech or "").lower(), {})
    exposure = ctx.get("exposure", "internal")
    hosting = ctx.get("hosting_type", "on_prem")
    raw = cve.cve_score or 0.0
    exposure_mult = EXPOSURE_MULTIPLIER.get(exposure, 1.0)
    hosting_mult = HOSTING_MULTIPLIER.get(hosting, 1.0)
    adjusted = round(min(10.0, raw * exposure_mult * hosting_mult), 1) if raw else 0.0

    return CveOut(
        id=cve.id,
        cve_id=cve.cve_id,
        tech=cve.tech or "",
        link=cve.link or "",
        summary=cve.summary or "",
        published=cve.published.isoformat() if cve.published else "",
        reference=[CveReferenceOut(url=r.url) for r in cve.references],
        affected=[a.affected for a in cve.affected],
        solutions=cve.solutions or "",
        cve_score=raw,
        cve_severity=cve.cve_severity or "",
        cvss_vector=cve.cvss_vector or "",
        last_updated=cve.updated_at.isoformat() if cve.updated_at else "",
        poc_available=cve.poc_available,
        pocs=[
            CvePocOut(url=p.url, source=p.source or "", poc_type=p.poc_type or "poc")
            for p in cve.pocs
        ],
        false_positive=is_fp,
        detected_on=cve.detected_on.isoformat() if cve.detected_on else "",
        news_mentions_count=len(mentions),
        news_mentions=mentions,
        tech_exposure=exposure,
        hosting_type=hosting,
        adjusted_risk_score=adjusted,
        cisa_kev=cve.cisa_kev,
        active_exploitation=cve.active_exploitation,
        epss_score=cve.epss_score,
        epss_percentile=cve.epss_percentile,
    )


async def _active_tech_names(session: AsyncSession, client_id: str) -> list[str] | None:
    """Tech yang tampil di tab CVEs/stats/dashboard/export: entri AKTIF client ini.

    `None` = client belum punya entri sama sekali (tanpa filter tech, perilaku lama). `[]` = punya
    entri tapi semuanya nonaktif (disembunyikan, ROADMAP #19): tab kosong, BUKAN tanpa filter.
    Baris `cve_tracker` entri nonaktif tidak dihapus; ticket-nya tetap."""
    return await AsyncTechStackRepo(session).visible_names(client_id)


@router.get("", response_model=CveListResponse)
async def list_cves(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tech: list[str] | None = Query(None),
    severity: list[str] | None = Query(None),
    search: str | None = None,
    date_start: datetime.date | None = None,
    date_end: datetime.date | None = None,
    include_fp: bool = False,
    sort_by: str = Query("published", pattern="^(tech|severity|published|epss)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    ack_filter: str | None = Query(None, pattern=_ACK_FILTER_PATTERN),
    date_basis: str = Query("published", pattern=_DATE_BASIS_PATTERN),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> CveListResponse:
    cid = effective_client_id(user, x_client_id)
    fp_repo = AsyncCveFalsePositiveRepo(session)
    fp_ids = await fp_repo.list_cve_ids(cid)
    fp_ids_set = set(fp_ids)

    effective_tech = tech or await _active_tech_names(session, cid)
    tracker_repo = AsyncCveTrackerRepo(session)
    cves, total = await tracker_repo.list_filtered(
        client_id=cid,
        page=page,
        page_size=page_size,
        tech=effective_tech,
        severity=severity,
        search=search,
        date_start=date_start,
        date_end=date_end,
        exclude_cve_ids=None if include_fp else fp_ids,
        sort_by=sort_by,
        sort_dir=sort_dir,
        ack_filter=ack_filter,
        date_basis=date_basis,
    )

    tp_ids = [c.cve_id for c in cves if c.cve_id not in fp_ids_set]
    mentions_map = await tracker_repo.get_article_mentions(tp_ids)
    risk_ctx = await AsyncTechStackRepo(session).get_risk_context(cid)

    return CveListResponse(
        cves=[
            _serialize(
                c,
                is_fp=c.cve_id in fp_ids_set,
                mentions=mentions_map.get(c.cve_id, []),
                risk_ctx=risk_ctx,
            )
            for c in cves
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=CveStats)
async def cve_stats(
    include_fp: bool = False,
    search: str | None = Query(None),
    severity: list[str] | None = Query(None),
    tech: list[str] | None = Query(None),
    date_start: datetime.date | None = Query(None),
    date_end: datetime.date | None = Query(None),
    ack_filter: str | None = Query(None, pattern=_ACK_FILTER_PATTERN),
    date_basis: str = Query("published", pattern=_DATE_BASIS_PATTERN),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> CveStats:
    cid = effective_client_id(user, x_client_id)
    fp_ids = await AsyncCveFalsePositiveRepo(session).list_cve_ids(cid) if not include_fp else []
    effective_tech = tech or await _active_tech_names(session, cid)
    stats = await AsyncCveTrackerRepo(session).get_stats(
        client_id=cid,
        tech=effective_tech,
        severity=severity,
        search=search,
        date_start=date_start,
        date_end=date_end,
        exclude_cve_ids=fp_ids or None,
        ack_filter=ack_filter,
        date_basis=date_basis,
    )
    return CveStats(**stats)


@router.get("/dashboard", response_model=CveDashboard)
async def cve_dashboard(
    year: int | None = Query(None, ge=2000, le=2100),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> CveDashboard:
    """Dashboard MTTD/MTTA/MTTR per tahun (`detected_on`, WIB), scope sama dengan
    `/stats`: client aktif, techstack aktif, tanpa false-positive -- total di sini
    = total di tab CVEs. `year` kosong = tahun berjalan. Definisi metrik:
    `cti_api.services.cve_dashboard`."""
    cid = effective_client_id(user, x_client_id)
    fp_ids = await AsyncCveFalsePositiveRepo(session).list_cve_ids(cid)
    return await cve_dashboard_service.get_dashboard(
        session,
        client_id=cid,
        year=year,
        tech=await _active_tech_names(session, cid),
        exclude_cve_ids=fp_ids or None,
    )


@router.get("/freshness", response_model=CveFreshness)
async def cve_freshness(
    new_since: datetime.datetime | None = Query(None),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> CveFreshness:
    """ "Diupdate per kapan" untuk tab CVEs: kapan cek terakhir yang sukses (scraper `new_cve`, atau
    mirror CVE List V5 bila `live`), apakah ada cek yang sedang berjalan, dan CVE terbaru yang
    tercatat. `new_since` (ISO) menambah jumlah CVE baru sejak waktu itu: dipakai UI untuk
    melaporkan hasil cek manual. Lingkup CVE = tab CVEs (client aktif, tech dimonitor, tanpa FP)."""
    cid = effective_client_id(user, x_client_id)
    fp_ids = await AsyncCveFalsePositiveRepo(session).list_cve_ids(cid)
    return await cve_check_service.get_freshness(
        session,
        client_id=cid,
        tech=await _active_tech_names(session, cid),
        exclude_cve_ids=fp_ids or None,
        new_since=new_since,
    )


@router.post("/check-new", response_model=CveCheckTriggered)
async def check_new_cves(
    request: Request,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    user: AuthedUser = Depends(require_admin),
) -> CveCheckTriggered:
    """Cek CVE terbaru SEKARANG untuk tech yang dimonitor: mengirim tugas cek rutin (scraper
    `new_cve`, atau `cve.mirror_sync` bila mirror `live`) ke worker; hasilnya tampil lewat
    `GET /freshness`. Hanya admin (kuota NVD/MITRE, sama dengan trigger scraper). Ditolak 409 bila
    cek sedang berjalan atau scraper dimatikan, 429 selama cooldown, 503 bila worker tak
    terjangkau."""
    try:
        result = await cve_check_service.trigger_check(session, redis)
    except cve_check_service.CheckAlreadyRunning:
        raise HTTPException(status_code=409, detail="A CVE check is already running") from None
    except cve_check_service.CheckUnavailable as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except cve_check_service.CheckCooldown as e:
        raise HTTPException(
            status_code=429,
            detail=f"A check was triggered recently, try again in {e.seconds} seconds",
            headers={"Retry-After": str(e.seconds)},
        ) from None
    except cve_check_service.CheckBrokerError:
        raise HTTPException(
            status_code=503, detail="Worker is unreachable (broker down), try again shortly"
        ) from None
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="check_new_cves",
        detail={"sources": result.sources},
        ip_address=request_ip(request),
    )
    await session.commit()
    return result


@router.get("/tech-list")
async def tech_list(
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> list[str]:
    cid = effective_client_id(user, x_client_id)
    techs = await AsyncCveTrackerRepo(session).get_tech_list(cid)
    hidden = await AsyncTechStackRepo(session).inactive_names(cid)
    return [t for t in techs if t not in hidden]


@router.post("/{cve_id}/false-positive")
async def set_false_positive(
    cve_id: CveId,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, bool]:
    cid = effective_client_id(user, x_client_id)
    await AsyncCveFalsePositiveRepo(session).mark(cve_id, cid, marked_by=user["username"])
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="mark_false_positive",
        target_id=cve_id,
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True}


@router.delete("/{cve_id}/false-positive")
async def remove_false_positive(
    cve_id: CveId,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, bool]:
    cid = effective_client_id(user, x_client_id)
    await AsyncCveFalsePositiveRepo(session).unmark(cve_id, cid)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="unmark_false_positive",
        target_id=cve_id,
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True}


@router.post("/bulk-false-positive")
async def set_bulk_false_positive(
    body: BulkFalsePositiveBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    cve_ids = body.cve_ids
    if not cve_ids:
        return {"ok": False, "detail": "cve_ids required"}
    if len(cve_ids) > 100:
        return {"ok": False, "detail": "max 100 CVEs per bulk operation"}
    cid = effective_client_id(user, x_client_id)
    marked = await AsyncCveFalsePositiveRepo(session).bulk_mark(
        cve_ids, cid, marked_by=user["username"]
    )
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="bulk_mark_false_positive",
        detail={"cve_ids": cve_ids, "count": marked},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True, "marked": marked}


@router.post("/purge-orphaned")
async def purge_orphaned(
    body: PurgeOrphanedBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_admin),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    """Hapus CVE yang tech-nya UDAH GAK ADA di techstack aktif client ini.
    `{"dry_run": false}` buat beneran eksekusi -- default preview doang.

    **Hanya admin/superadmin**, termasuk preview-nya: eksekusi menghapus baris `cve_tracker` dan
    penanda FP-nya secara permanen (client tanpa techstack: semua CVE dianggap yatim)."""
    dry_run = body.dry_run
    cid = effective_client_id(user, x_client_id)
    # Semua entri, termasuk yang nonaktif: yang disembunyikan BUKAN yatim, barisnya tidak boleh
    # ikut terhapus. (`[]` = client tanpa entri: semua dianggap yatim, port perilaku lama.)
    active_names = await AsyncTechStackRepo(session).all_names(cid)
    result = await AsyncCveTrackerRepo(session).purge_orphaned(
        client_id=cid, active_tech_names=active_names, dry_run=dry_run
    )
    if not dry_run:
        await AsyncAuditLogRepo(session).write(
            username=user["username"],
            action="purge_orphaned_cves",
            detail={"deleted": result.get("deleted", 0), "by_tech": result.get("by_tech")},
            ip_address=request_ip(request),
        )
    await session.commit()
    return result


@router.post("/cisa-lookup")
async def cisa_kev_lookup(
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    """Cross-reference semua CVE true-positive vs katalog CISA Known
    Exploited Vulnerabilities."""
    try:
        summary = await cve_lookup_service.run_cisa_kev_lookup(session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="cisa_kev_lookup",
        detail={"checked": summary["checked"], "matched": summary["matched"]},
        ip_address=request_ip(request),
    )
    await session.commit()
    return summary


@router.post("/epss-lookup")
async def epss_lookup(
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    """Fetch skor EPSS dari FIRST.org buat semua CVE true-positive, simpen
    hasilnya."""
    try:
        summary = await cve_lookup_service.run_epss_lookup(session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="epss_lookup",
        detail={"checked": summary["checked"], "scored": summary["scored"]},
        ip_address=request_ip(request),
    )
    await session.commit()
    return summary


@router.post("/exploit-lookup")
async def bulk_exploit_lookup(
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    """Exploit-db lookup buat semua CVE true-positive, simpen hasilnya."""
    try:
        summary = await cve_lookup_service.run_exploit_db_bulk_lookup(session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="exploit_db_bulk_lookup",
        detail={"checked": summary["checked"], "with_exploits": summary["with_exploits"]},
        ip_address=request_ip(request),
    )
    await session.commit()
    return summary


@router.post("/{cve_id}/exploit-lookup")
async def single_exploit_lookup(
    cve_id: CveId,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    """Exploit-db lookup buat satu CVE, simpen hasilnya."""
    result = await cve_lookup_service.run_exploit_db_single_lookup(session, cve_id)
    if result["error"]:
        raise HTTPException(status_code=500, detail=str(result["error"]))
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="exploit_db_lookup",
        target_id=cve_id,
        ip_address=request_ip(request),
    )
    await session.commit()
    return result


@router.get("/export")
async def export_cves(
    request: Request,
    date_start: datetime.date | None = Query(None),
    date_end: datetime.date | None = Query(None),
    search: str | None = Query(None),
    severity: list[str] | None = Query(None),
    tech: list[str] | None = Query(None),
    include_fp: bool = Query(False),
    ack_filter: str | None = Query(None, pattern=_ACK_FILTER_PATTERN),
    date_basis: str = Query("detected", pattern=_DATE_BASIS_PATTERN),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> StreamingResponse:
    """Export CVE+ticket client ini sebagai Excel. Lihat docstring
    `cti_api.services.cve_export` -- SEKARANG di-scope `client_id`
    (legacy: bug, gak pernah nge-scope sama sekali)."""
    cid = effective_client_id(user, x_client_id)
    try:
        data = await cve_export_service.export_cves_to_excel(
            session,
            client_id=cid,
            date_start=date_start,
            date_end=date_end,
            search=search,
            severity=severity,
            # Scope SAMA dengan tab CVEs (`docs/CVE_TRACKER_FLOW.md` 10.8): entri nonaktif
            # (disembunyikan) tidak ikut export. Dulu export tidak menyaring techstack sama sekali.
            tech=tech or await _active_tech_names(session, cid),
            include_fp=include_fp,
            ack_filter=ack_filter,
            date_basis=date_basis,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    filename = f"CVE_Tracker_Export_{datetime.date.today().strftime('%Y%m%d')}.xlsx"
    if date_start or date_end:
        filename = f"CVE_Tracker_{date_start or 'start'}_{date_end or 'end'}.xlsx"

    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="export_cve_excel",
        detail={
            "date_start": date_start.isoformat() if date_start else None,
            "date_end": date_end.isoformat() if date_end else None,
            "search": search,
            "severity": severity,
            "tech": tech,
            "ack_filter": ack_filter,
            "date_basis": date_basis,
        },
        ip_address=request_ip(request),
    )
    await session.commit()
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/next-ticket-id")
async def next_ticket_id(
    session: AsyncSession = Depends(get_db), _user: AuthedUser = Depends(require_auth)
) -> dict[str, str]:
    return {"ticket_id": await AsyncCveTicketRepo(session).get_next_ticket_id()}


@router.get("/ack-statuses")
async def ack_statuses(
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, str]:
    cid = effective_client_id(user, x_client_id)
    return await AsyncCveTicketRepo(session).get_ack_statuses(cid)


@router.post("/draft-email")
async def create_draft_email(
    body: DraftEmailBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    if not body.cve_ids:
        raise HTTPException(status_code=400, detail="cve_ids required")
    cid = effective_client_id(user, x_client_id)
    ticket_repo = AsyncCveTicketRepo(session)
    ticket_id = (
        body.ticket_id
        or await ticket_repo.tracking_id_for(body.cve_ids, cid)
        or await ticket_repo.get_next_ticket_id()
    )
    try:
        result = await cve_email_service.draft_email_for_cves(
            session, body.cve_ids, ticket_id, client_id=cid
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="draft_email",
        detail={"cve_ids": body.cve_ids},
        ip_address=request_ip(request),
    )
    await session.commit()
    return result


@router.get("/tickets")
async def list_cve_tickets(
    search: str | None = Query(None),
    status: str | None = Query(None),
    include_fp: bool = False,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    """Daftar ticket client ini (view "Ticketing" di CVE Tracker) --
    `_serialize_ticket` + ringkasan CVE-nya (severity/score/tech/
    detected_on) biar tabel gak perlu N request.

    Ticket CVE false positive disembunyikan (konsisten dengan tab CVEs, dashboard, dan export)
    kecuali `include_fp=true`; UI mewajibkan Acknowledge sebelum Mark FP, jadi tiap CVE FP punya
    ticket."""
    cid = effective_client_id(user, x_client_id)
    fp_ids = await AsyncCveFalsePositiveRepo(session).list_cve_ids(cid)
    rows = await AsyncCveTicketRepo(session).list_with_cve(
        cid, search=search, status=status, exclude_cve_ids=None if include_fp else fp_ids
    )
    fp_set = set(fp_ids)
    tickets: list[dict[str, object]] = []
    for ticket, cve in rows:
        item = _serialize_ticket(ticket)
        item["false_positive"] = ticket.cve_id in fp_set
        item["cve_severity"] = (cve.cve_severity if cve else "") or ""
        item["cve_score"] = (cve.cve_score if cve else None) or 0.0
        item["tech"] = (cve.tech if cve else "") or ""
        item["detected_on"] = cve.detected_on.isoformat() if cve and cve.detected_on else ""
        tickets.append(item)
    return {"tickets": tickets, "total": len(tickets)}


@router.get("/{cve_id}/ticket")
async def get_cve_ticket(
    cve_id: CveId,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    ticket = await AsyncCveTicketRepo(session).get(cve_id, cid)
    return _serialize_ticket(ticket)


@router.put("/{cve_id}/ticket")
async def update_cve_ticket(
    cve_id: CveId,
    body: CveTicketBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, bool]:
    cid = effective_client_id(user, x_client_id)
    await AsyncCveTicketRepo(session).upsert(
        cve_id=cve_id,
        client_id=cid,
        affected_asset=body.affected_asset or None,
        affected_version=body.affected_version or None,
        fixed_version=body.fixed_version or None,
        asset_owner=body.asset_owner or None,
        owner_email=body.owner_email or None,
        owner_team=body.owner_team or None,
        active_exploitation=body.active_exploitation or None,
        remediation_date_plan=_parse_date(body.remediation_date_plan),
        remediation_status=body.remediation_status or None,
        actual_remediation_date=_parse_date(body.actual_remediation_date),
        escalation_required=body.escalation_required,
        comments=body.comments or None,
        risk_acceptance=body.risk_acceptance or None,
        closure_date=_parse_date(body.closure_date),
    )
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="update_ticket",
        target_id=cve_id,
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True}


@router.post("/bulk-acknowledge")
async def bulk_acknowledge(
    body: BulkAcknowledgeBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    if not body.cve_ids:
        raise HTTPException(status_code=400, detail="cve_ids required")
    if not body.analyst_name.strip():
        raise HTTPException(status_code=400, detail="analyst_name required")
    if len(body.cve_ids) > 100:
        raise HTTPException(status_code=400, detail="max 100 CVEs per bulk operation")
    cid = effective_client_id(user, x_client_id)
    acknowledged = await AsyncCveTicketRepo(session).bulk_acknowledge(
        body.cve_ids, cid, body.analyst_name
    )
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="bulk_acknowledge_cve",
        detail={
            "cve_ids": body.cve_ids,
            "analyst_name": body.analyst_name,
            "acknowledged": acknowledged,
        },
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True, "acknowledged": acknowledged}


@router.post("/{cve_id}/acknowledge")
async def acknowledge(
    cve_id: CveId,
    body: AcknowledgeBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, bool]:
    if not body.analyst_name.strip():
        raise HTTPException(status_code=400, detail="analyst_name required")
    cid = effective_client_id(user, x_client_id)
    await AsyncCveTicketRepo(session).acknowledge(cve_id, cid, body.analyst_name)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="acknowledge_cve",
        target_id=cve_id,
        detail={"analyst_name": body.analyst_name},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"ok": True}


@router.get("/prioritize")
async def prioritize_cves(
    cves: str = Query(..., description="Comma-separated CVE IDs"),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    """Ad-hoc CVE prioritization di luar konteks campaign apa pun."""
    cid = effective_client_id(user, x_client_id)
    cve_list = [c.strip() for c in cves.split(",") if c.strip()]
    if not cve_list:
        raise HTTPException(status_code=400, detail="cves query param required")
    if len(cve_list) > 100:
        raise HTTPException(status_code=400, detail="Max 100 CVEs per request")
    result = await cve_priority_service.prioritize_campaign_cves(session, cve_list, client_id=cid)
    return {"cves": result, "total": len(result)}
