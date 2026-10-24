"""Port dari `ScraperNewsWeb/app/routers/crossref.py`. SELURUH router
ini butuh `view_intel` (deklarasi level-router). `pir_id` sekarang `int` (path param), BUKAN
`str` ObjectId -- FastAPI validasi tipe otomatis, gak butuh try/except `ObjectId(...)`
kayak kode lama. CVE tracker dan PIR di-scope ke client aktif (`X-Client-ID`), lihat docstring
`cti_api.services.crossref`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, effective_client_id, get_db, require_auth, require_permission
from cti_api.services import crossref as crossref_service

router = APIRouter(
    prefix="/api/crossref",
    tags=["crossref"],
    dependencies=[Depends(require_permission("view_intel")), Depends(require_auth)],
)


@router.get("/cve/{cve_id}")
async def cve_crossref(
    cve_id: str,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    result = await crossref_service.get_cve_crossrefs(session, cve_id, cid)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/pir/{pir_id}")
async def pir_crossref(
    pir_id: int,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    result = await crossref_service.get_pir_crossrefs(session, pir_id, cid)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/ta/{actor_name:path}")
async def ta_crossref(
    actor_name: str,
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    return await crossref_service.get_ta_crossrefs(session, actor_name, cid)
