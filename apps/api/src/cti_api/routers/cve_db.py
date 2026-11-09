"""CVE DB (ROADMAP #19, irisan 5): penjelajah baca-saja atas mirror CVE (`cve_records`), terpisah
dari tab CVEs (`cve_tracker` = hanya CVE untuk tech yang di-Monitor). Dari satu CVE, tiap produk
terdampak menampilkan status Monitor client ini sehingga UI bisa menawarkan aksi Monitor.

Mirror dibuang retensi tahun kalender (tahun berjalan dan sebelumnya); CVE yang sudah masuk
`cve_tracker` tetap ada di sana setelah terpangkas di sini."""

from __future__ import annotations

import contextlib
import datetime

from cti_core.config import get_settings
from cti_core.cve_mirror_sync import STATE_KEY, SyncState
from cti_core.db.models.cve_mirror import CveRecord
from cti_core.db.models.report_state import JobState
from cti_core.db.repositories.catalog_read import AsyncCatalogRepo, CveDbRow
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    effective_client_id,
    get_db,
    get_redis,
    require_auth,
    require_permission,
)
from cti_api.schemas.catalog import (
    CveDbDetail,
    CveDbListResponse,
    CveDbMeta,
    CveDbOut,
    CveDbProductOut,
)

router = APIRouter(
    prefix="/api/cve-db", tags=["cve-db"], dependencies=[Depends(require_permission("view_cve"))]
)

_SUMMARY_LIMIT = 400
_TOTAL_KEY = "cve_db:total"
_TOTAL_TTL = 300


def _products(row: CveDbRow) -> list[CveDbProductOut]:
    out = []
    for p in row.products:
        ref = p.monitor or p.vendor_monitor
        out.append(
            CveDbProductOut(
                vendor_id=p.vendor_id,
                vendor=p.vendor,
                family_id=p.family_id,
                family=p.family,
                monitored=ref is not None,
                monitor_entry_id=ref.entry_id if ref else None,
                covered_by_vendor=p.vendor_monitor is not None,
            )
        )
    return out


def _out(row: CveDbRow) -> CveDbOut:
    r = row.record
    summary = r.summary if len(r.summary) <= _SUMMARY_LIMIT else r.summary[:_SUMMARY_LIMIT] + "..."
    return CveDbOut(
        cve_id=r.cve_id,
        summary=summary,
        published_date=r.published_date,
        cvss_score=r.cvss_score,
        cvss_severity=r.cvss_severity,
        has_identity=r.has_identity,
        products=_products(row),
    )


@router.get("", response_model=CveDbListResponse)
async def list_cve_db(
    q: str | None = Query(None, max_length=200),
    vendor: int | None = Query(None, description="id vendor katalog"),
    family: int | None = Query(None, description="id keluarga katalog"),
    severity: list[str] | None = Query(None),
    date_start: datetime.date | None = None,
    date_end: datetime.date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> CveDbListResponse:
    cid = effective_client_id(user, x_client_id)
    result = await AsyncCatalogRepo(session).list_cves(
        client_id=cid,
        q=q,
        vendor_id=vendor,
        family_id=family,
        severity=severity,
        date_start=date_start,
        date_end=date_end,
        page=page,
        page_size=page_size,
    )
    return CveDbListResponse(
        items=[_out(r) for r in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/meta", response_model=CveDbMeta)
async def get_cve_db_meta(
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> CveDbMeta:
    """Baris kecil di atas CVE DB: total mirror, sinkron terakhir, dan apakah mirror menyala.
    `total` = `count(*)` atas jutaan baris, jadi di-cache `_TOTAL_TTL` detik; gagal Redis tidak
    boleh menjatuhkan endpoint (jatuh ke hitung langsung)."""
    total: int | None = None
    try:
        raw = await redis.get(_TOTAL_KEY)
        total = int(raw) if raw is not None else None
    except Exception:
        total = None
    if total is None:
        total = (await session.execute(select(func.count()).select_from(CveRecord))).scalar_one()
        with contextlib.suppress(Exception):
            await redis.set(_TOTAL_KEY, str(total), ex=_TOTAL_TTL)
    row = await session.get(JobState, STATE_KEY)
    polled = SyncState.load(row.value if row is not None else None).polled_at
    return CveDbMeta(total=total, last_sync_at=polled, enabled=get_settings().cve_mirror.enabled)


@router.get("/{cve_id}", response_model=CveDbDetail)
async def get_cve_db(
    cve_id: str,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> CveDbDetail:
    cid = effective_client_id(user, x_client_id)
    row = await AsyncCatalogRepo(session).get_cve(cve_id.upper(), cid)
    if row is None:
        raise HTTPException(status_code=404, detail="CVE not found in mirror")
    r = row.record
    return CveDbDetail(
        cve_id=r.cve_id,
        summary=r.summary,
        published_date=r.published_date,
        cvss_score=r.cvss_score,
        cvss_severity=r.cvss_severity,
        has_identity=r.has_identity,
        products=_products(row),
        link=r.link,
        solutions=r.solutions,
        cvss_vector=r.cvss_vector,
        reference_urls=list(r.reference_urls),
        affected_lines=list(r.affected_lines),
        modified_at=r.modified_at,
        published_at=r.published_at,
    )
