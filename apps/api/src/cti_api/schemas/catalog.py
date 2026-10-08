"""Skema API katalog tech dan CVE DB (ROADMAP #19, irisan 5; `docs/CVE_CATALOG_DESIGN.md` 7).

Katalog dan mirror global; yang per client hanyalah status Monitor (`monitored`,
`monitor_entry_id`, `covered_by_vendor`). Tanggal `YYYY-MM-DD` atau kosong (konvensi techstack)."""

from __future__ import annotations

import datetime

from pydantic import BaseModel


class CatalogVendorOut(BaseModel):
    id: int
    key: str
    display_name: str
    monitorable: bool
    """False untuk "(tanpa vendor)": hanya keluarganya yang bisa di-Monitor."""
    family_count: int
    visible_family_count: int
    """Keluarga dengan >= 2 CVE (yang tampil di tampilan jelajah)."""
    cve_seen_total: int
    first_seen: datetime.date | None = None
    last_cve_at: datetime.date | None = None
    monitored: bool
    """Sudah dirujuk target vendor di Monitor client ini (aktif atau nonaktif)."""
    monitor_entry_id: int | None = None


class CatalogFamilyOut(BaseModel):
    id: int
    vendor_id: int
    vendor_name: str
    key: str
    display_name: str
    source: str
    cve_seen_total: int
    """CVE unik yang pernah menyebut keluarga ini (monoton naik, tidak turun oleh retensi)."""
    first_seen: datetime.date | None = None
    last_cve_at: datetime.date | None = None
    monitored: bool
    monitor_entry_id: int | None = None
    covered_by_vendor: bool = False
    """Vendor keluarga ini sudah di-Monitor di tingkat vendor."""


class CatalogVendorListResponse(BaseModel):
    items: list[CatalogVendorOut]
    total: int
    page: int
    page_size: int
    hidden: int = 0
    """Berapa vendor disembunyikan aturan jelajah (0 bila `q` atau `show_all`)."""


class CatalogFamilyListResponse(BaseModel):
    items: list[CatalogFamilyOut]
    total: int
    page: int
    page_size: int
    hidden: int = 0
    """Berapa keluarga disembunyikan (hanya 1 CVE); `show_all=true` menampilkannya."""


class CveDbProductOut(BaseModel):
    vendor_id: int
    vendor: str
    family_id: int
    family: str
    monitored: bool
    """Keluarga ini sudah di-Monitor, langsung atau lewat target vendor."""
    monitor_entry_id: int | None = None


class CveDbOut(BaseModel):
    cve_id: str
    summary: str
    published_date: datetime.date
    cvss_score: float | None = None
    cvss_severity: str | None = None
    has_identity: bool
    products: list[CveDbProductOut] = []


class CveDbDetail(CveDbOut):
    link: str | None = None
    solutions: str | None = None
    cvss_vector: str | None = None
    reference_urls: list[str] = []
    affected_lines: list[str] = []
    modified_at: datetime.datetime | None = None
    published_at: datetime.datetime | None = None


class CveDbListResponse(BaseModel):
    items: list[CveDbOut]
    total: int
    page: int
    page_size: int
