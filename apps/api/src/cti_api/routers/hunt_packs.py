"""Hunting pack web (P7e spec 6.2): `GET /api/hunt-packs/{anchor_type}/{anchor_id}`, JWT +
`view_ioc`, tanpa filter TLP (user web belum punya clearance TLP; R1). `pack_response` dipakai
juga oleh route mesin `/api/v2` (filter TLP token)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import get_db, require_permission
from cti_api.schemas.hunt import HuntPackOut
from cti_api.services import hunt_pack

router = APIRouter(prefix="/api/hunt-packs", tags=["hunt-packs"])

AnchorType = Literal["story", "entity"]
Include = Literal["inferred", "llm"]
ZIP_RESPONSE: dict[int | str, dict[str, object]] = {
    200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}
}


async def pack_response(
    session: AsyncSession,
    anchor_type: AnchorType,
    anchor_id: int,
    *,
    include: list[Include],
    days: int,
    format_: Literal["json", "zip"],
    max_tlp: str | None,
) -> HuntPackOut | Response:
    """404 untuk anchor tak dikenal; merged -> 404 dengan `merged_into_id` di detail (handler
    `/api/v2` memindahkannya ke `error.details`)."""
    inc: set[str] = set(include)
    try:
        if format_ == "zip":
            data = await hunt_pack.get_pack_zip(
                session, anchor_type, anchor_id, include=inc, days=days, max_tlp=max_tlp
            )
            return Response(
                data,
                media_type="application/zip",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="hunt-{anchor_type}-{anchor_id}.zip"'
                    )
                },
            )
        pack = await hunt_pack.get_pack(
            session, anchor_type, anchor_id, include=inc, days=days, max_tlp=max_tlp
        )
    except hunt_pack.AnchorNotFound:
        raise HTTPException(404, "Hunting pack anchor not found") from None
    except hunt_pack.AnchorMerged as e:
        raise HTTPException(
            404, {"message": "Entity was merged", "merged_into_id": e.into_id}
        ) from None
    return HuntPackOut.model_validate(pack)


@router.get(
    "/{anchor_type}/{anchor_id}",
    response_model=HuntPackOut,
    responses=ZIP_RESPONSE,
    dependencies=[Depends(require_permission("view_ioc"))],
)
async def get_hunt_pack(
    anchor_type: AnchorType,
    anchor_id: int,
    include: list[Include] = Query([]),
    days: int = Query(90, ge=1, le=365),
    format_: Literal["json", "zip"] = Query("json", alias="format"),
    session: AsyncSession = Depends(get_db),
) -> HuntPackOut | Response:
    return await pack_response(
        session, anchor_type, anchor_id, include=include, days=days, format_=format_, max_tlp=None
    )
