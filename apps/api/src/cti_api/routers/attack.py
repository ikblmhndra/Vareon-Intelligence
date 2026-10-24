"""Port dari `ScraperNewsWeb/app/routers/attack.py` -- SELURUH router ini
`require_auth` (deklarasi level-router, sama kayak legacy), gak ada
asimetri baca-vs-tulis di sini (beda dari `articles.py`/`pir.py` dkk).

`POST /sync`/`GET /sync/{domain_key}` pakai `BackgroundTasks` FastAPI --
port apa adanya, INI BUKAN salah satu dari 5 loop yang pindah ke Celery
beat (Fase 7.8): itu loop KONTINYU yang jalan otomatis, ini aksi ADMIN
SEKALI-PAKAI yang di-trigger manual (analog "tombol Sync" di UI). Sama
keterbatasan kayak kode lama: task-nya jalan DALAM proses `apps/api`,
gak selamat restart/gak sinkron lintas >1 worker uvicorn -- kalau nanti
mau diperbaiki, itu keputusan terpisah (pindah ke Celery task biasa,
bukan beat), bukan bagian dari porting apa adanya di sini.

Background task butuh SESSION SENDIRI (`async_session()` langsung, BUKAN
`Depends(get_db)`) -- sesi yang di-inject ke endpoint ditutup begitu
response dikirim, background task jalan SETELAH itu."""

from __future__ import annotations

from cti_core.db.engine import async_session
from cti_core.db.repositories.attack import DOMAINS, AsyncAttackQueryRepo, AsyncAttackSyncRepo
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    get_db,
    request_ip,
    require_auth,
    require_permission,
)

router = APIRouter(
    prefix="/api/attack",
    tags=["attack"],
    dependencies=[Depends(require_permission("view_intel")), Depends(require_auth)],
)


class SyncRequest(BaseModel):
    domains: list[str] | None = None


async def _run_sync(domain_keys: list[str]) -> None:
    async with async_session() as session:
        repo = AsyncAttackSyncRepo(session)
        for key in domain_keys:
            try:
                await repo.sync_domain(key)
            except Exception as e:
                # Port apa adanya -- legacy juga nelen semua exception di
                # background task ini, cuma di-print, gak di-reraise.
                print(f"[ATT&CK sync] {key} failed: {e}")


@router.get("/status")
async def attack_status(session: AsyncSession = Depends(get_db)) -> list[dict[str, object]]:
    return await AsyncAttackSyncRepo(session).get_sync_status()


@router.post("/sync")
async def attack_sync(
    body: SyncRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_permission("manage_intel")),
) -> dict[str, object]:
    domains = body.domains if body.domains else list(DOMAINS.keys())
    invalid = [d for d in domains if d not in DOMAINS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown domains: {invalid}")

    background_tasks.add_task(_run_sync, domains)
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="attack_sync",
        detail={"domains": domains},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"status": "started", "domains": domains}


@router.get("/sync/{domain_key}")
async def attack_sync_single(
    domain_key: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_permission("manage_intel")),
) -> dict[str, object]:
    if domain_key not in DOMAINS:
        raise HTTPException(status_code=404, detail=f"Unknown domain: {domain_key}")

    background_tasks.add_task(_run_sync, [domain_key])
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="attack_sync",
        detail={"domains": [domain_key]},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"status": "started", "domain": domain_key}


@router.get("/techniques")
async def list_techniques(
    domain: str | None = Query(None),
    tactic: str | None = Query(None),
    search: str | None = Query(None),
    is_subtechnique: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    docs, total = await AsyncAttackQueryRepo(session).get_techniques(
        domain=domain,
        tactic=tactic,
        search=search,
        is_subtechnique=is_subtechnique,
        page=page,
        page_size=page_size,
    )
    return {"techniques": docs, "total": total, "page": page, "page_size": page_size}


@router.get("/tactics/distinct")
async def distinct_tactics(
    domain: str | None = Query(None), session: AsyncSession = Depends(get_db)
) -> list[str]:
    return await AsyncAttackQueryRepo(session).get_distinct_tactics_field(domain=domain)


@router.get("/techniques/{attack_id}")
async def get_technique(
    attack_id: str, session: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    doc = await AsyncAttackQueryRepo(session).get_technique(attack_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Technique not found")
    return doc


@router.get("/tactics")
async def list_tactics(
    domain: str | None = Query(None), session: AsyncSession = Depends(get_db)
) -> list[dict[str, object]]:
    return await AsyncAttackQueryRepo(session).get_tactics(domain=domain)


@router.get("/mitigations")
async def list_mitigations(
    domain: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    docs, total = await AsyncAttackQueryRepo(session).get_mitigations(
        domain=domain, search=search, page=page, page_size=page_size
    )
    return {"mitigations": docs, "total": total, "page": page, "page_size": page_size}


@router.get("/groups")
async def list_groups(
    domain: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    docs, total = await AsyncAttackQueryRepo(session).get_groups(
        domain=domain, search=search, page=page, page_size=page_size
    )
    return {"groups": docs, "total": total, "page": page, "page_size": page_size}


@router.get("/groups/{group_id}")
async def get_group(group_id: str, session: AsyncSession = Depends(get_db)) -> dict[str, object]:
    doc = await AsyncAttackQueryRepo(session).get_group(group_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Group not found")
    return doc


@router.get("/software")
async def list_software(
    domain: str | None = Query(None),
    sw_type: str | None = Query(None, alias="type"),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    docs, total = await AsyncAttackQueryRepo(session).get_software(
        domain=domain, sw_type=sw_type, search=search, page=page, page_size=page_size
    )
    return {"software": docs, "total": total, "page": page, "page_size": page_size}


@router.get("/software/{software_id}")
async def get_software_item(
    software_id: str, session: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    doc = await AsyncAttackQueryRepo(session).get_software_item(software_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Software not found")
    return doc


@router.get("/navigator-layer")
async def attack_navigator_layer(
    domain: str | None = Query(None),
    tactic: str | None = Query(None),
    search: str | None = Query(None),
    is_subtechnique: bool | None = Query(None),
    group_id: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    layer = await AsyncAttackQueryRepo(session).get_navigator_layer(
        domain=domain,
        tactic=tactic,
        search=search,
        is_subtechnique=is_subtechnique,
        group_id=group_id,
    )
    return JSONResponse(content=layer)
