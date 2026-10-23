"""`GET /api/data-health` -- halaman Data health (ROADMAP #24 PR-B). Baca saja, semua user login
(sama seperti `/api/scraper/health`); logikanya di `cti_api.services.data_health`."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import get_db, get_redis, require_auth
from cti_api.schemas.data_health import DataHealthOut
from cti_api.services.data_health import get_data_health

router = APIRouter(
    prefix="/api/data-health", tags=["data-health"], dependencies=[Depends(require_auth)]
)


@router.get("", response_model=DataHealthOut)
async def data_health(
    session: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)
) -> DataHealthOut:
    return await get_data_health(session, redis)
