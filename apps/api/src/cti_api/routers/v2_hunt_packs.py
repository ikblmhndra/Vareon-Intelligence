"""Hunting pack mesin (P7e spec 6.1): `GET /api/v2/hunt-packs/{anchor_type}/{anchor_id}`,
`require_token("hunt:read")`, indikator difilter `max_tlp` token. Galat berbentuk v2
(`{error: {code, message, details}}`) lewat handler `/api/v2` di `errors.py`."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import get_db
from cti_api.machine_auth import MachinePrincipal, require_token
from cti_api.routers.hunt_packs import ZIP_RESPONSE, AnchorType, Include, pack_response
from cti_api.schemas.hunt import HuntPackOut

router = APIRouter(prefix="/api/v2/hunt-packs", tags=["machine-api"])


@router.get("/{anchor_type}/{anchor_id}", response_model=HuntPackOut, responses=ZIP_RESPONSE)
async def get_hunt_pack_v2(
    anchor_type: AnchorType,
    anchor_id: int,
    include: list[Include] = Query([]),
    days: int = Query(90, ge=1, le=365),
    format_: Literal["json", "zip"] = Query("json", alias="format"),
    principal: MachinePrincipal = Depends(require_token("hunt:read")),
    session: AsyncSession = Depends(get_db),
) -> HuntPackOut | Response:
    return await pack_response(
        session,
        anchor_type,
        anchor_id,
        include=include,
        days=days,
        format_=format_,
        max_tlp=principal.max_tlp,
    )
