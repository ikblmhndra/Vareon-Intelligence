"""Katalog tech (ROADMAP #19, irisan 5; `docs/CVE_CATALOG_DESIGN.md` 7): vendor -> keluarga produk
dari CVE List V5, untuk tab All Tech. Baca-saja dan GLOBAL; yang per client hanya status Monitor.

Tampilan jelajah menyembunyikan keluarga yang hanya punya 1 CVE (`show_all=true` menampilkan
semuanya); pencarian (`q`) tidak menyembunyikan apa pun. Pagination wajib (14 ribu vendor, 37 ribu
keluarga)."""

from __future__ import annotations

from cti_core.db.repositories.catalog_read import (
    AsyncCatalogRepo,
    FamilyRow,
    Page,
    VendorRow,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, effective_client_id, get_db, require_auth
from cti_api.schemas.catalog import (
    CatalogFamilyListResponse,
    CatalogFamilyOut,
    CatalogVendorListResponse,
    CatalogVendorOut,
)

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def _vendor_out(row: VendorRow) -> CatalogVendorOut:
    v = row.vendor
    return CatalogVendorOut(
        id=v.id,
        key=v.key,
        display_name=v.display_name,
        monitorable=v.monitorable,
        family_count=row.family_count,
        visible_family_count=row.visible_family_count,
        cve_seen_total=v.cve_seen_total,
        first_seen=v.first_seen,
        last_cve_at=v.last_cve_at,
        monitored=row.monitor is not None,
        monitor_entry_id=row.monitor.entry_id if row.monitor else None,
    )


def _family_out(row: FamilyRow) -> CatalogFamilyOut:
    f = row.family
    ref = row.monitor or row.vendor_monitor
    return CatalogFamilyOut(
        id=f.id,
        vendor_id=f.vendor_id,
        vendor_name=row.vendor.display_name,
        key=f.key,
        display_name=f.display_name,
        source=f.source,
        cve_seen_total=f.cve_seen_total,
        first_seen=f.first_seen,
        last_cve_at=f.last_cve_at,
        monitored=ref is not None,
        monitor_entry_id=ref.entry_id if ref else None,
        covered_by_vendor=row.vendor_monitor is not None,
    )


@router.get("/vendors", response_model=CatalogVendorListResponse)
async def list_vendors(
    q: str | None = Query(None, max_length=100),
    show_all: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> CatalogVendorListResponse:
    cid = effective_client_id(user, x_client_id)
    result = await AsyncCatalogRepo(session).list_vendors(
        client_id=cid, q=q, show_all=show_all, page=page, page_size=page_size
    )
    return CatalogVendorListResponse(
        items=[_vendor_out(r) for r in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        hidden=result.hidden,
    )


@router.get("/vendors/{vendor_id}/families", response_model=CatalogFamilyListResponse)
async def list_vendor_families(
    vendor_id: int,
    q: str | None = Query(None, max_length=100),
    show_all: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> CatalogFamilyListResponse:
    cid = effective_client_id(user, x_client_id)
    repo = AsyncCatalogRepo(session)
    if await repo.get_vendor(vendor_id) is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    result = await repo.list_families(
        client_id=cid,
        vendor_id=vendor_id,
        q=q,
        show_all=show_all,
        page=page,
        page_size=page_size,
    )
    return _family_response(result)


@router.get("/families", response_model=CatalogFamilyListResponse)
async def search_families(
    q: str = Query(..., min_length=2, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> CatalogFamilyListResponse:
    """Pencarian lintas vendor; tidak menyembunyikan keluarga ber-1 CVE."""
    cid = effective_client_id(user, x_client_id)
    result = await AsyncCatalogRepo(session).list_families(
        client_id=cid, q=q, page=page, page_size=page_size
    )
    return _family_response(result)


def _family_response(result: Page[FamilyRow]) -> CatalogFamilyListResponse:
    return CatalogFamilyListResponse(
        items=[_family_out(r) for r in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        hidden=result.hidden,
    )
