"""Adaptasi dari `ScraperNewsWeb/app/models/cve_tracker.py`. Field CISA-
KEV/EPSS (flat: `cisa_kev`/`active_exploitation`/`epss_score`/
`epss_percentile`) SEKARANG diekspos (Fase 7.4 Grup B) -- blob deskriptif
mentah (`cisa_kev_detail`/`exploit_db_hits`) SENGAJA belum, list view
tetap ringkas, lihat docstring `cti_api.routers.cve`. Field yang nempel
fitur campaign SENGAJA masih gak ada di sini (Grup A, plan §Fase 7.4).

`CveTicketBody` -- field remediation doang (14 field, semua `str=""`
kayak legacy, TANPA `Literal`/enum validation -- server-side legacy juga
gak validasi, cuma dropdown di frontend, lihat docstring `CveTicket`
model). Tanggal (`remediation_date_plan`/`actual_remediation_date`/
`closure_date`) tetap `str` di boundary API (`"YYYY-MM-DD"` atau kosong)
-- diparse ke `datetime.date` di router sebelum masuk repo (`Date` asli
di DB, lihat docstring model), balik jadi string lagi pas serialize.
`cve_reported_date`/`ticket_id`/`acknowledged_by`/`acknowledge_time`
SENGAJA gak ada di body PUT -- `ticket_id` di-generate/dipertahankan
server-side (`AsyncCveTicketRepo.upsert`), `acknowledged_by`/
`acknowledge_time` cuma nempel `acknowledge()`/`bulk_acknowledge()`,
`cve_reported_date` di-drop (lihat docstring model, derive dari
`CveTracker.published` di frontend)."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel

_CVE_ID = re.compile(r"cve-[0-9]{4}-[0-9]{4,11}", re.ASCII | re.IGNORECASE)
"""`CVE-YYYY-NNNN...`, maksimum 11 digit supaya muat di kolom `String(20)` (9 karakter awalan).
`[0-9]` + `re.ASCII`, bukan `\\d`: digit Unicode (mis. fullwidth) bukan CVE ID."""


def normalize_cve_id(value: str) -> str:
    """Huruf besar, spasi pinggir dibuang; `ValueError` kalau bukan CVE ID. Semua pencocokan
    `cve_id` di DB itu persis, jadi `cve-2026-1234` tanpa ini menjadi baris FP/ticket tersendiri
    yang tidak pernah ketemu, dan id yang kepanjangan untuk kolom berujung 500."""
    candidate = value.strip()
    if not _CVE_ID.fullmatch(candidate):
        raise ValueError(f"bukan CVE ID yang valid: {value!r}")
    return candidate.upper()


CveId = Annotated[str, AfterValidator(normalize_cve_id)]
"""Tipe untuk `cve_id` di path dan body request: sudah dinormalisasi dan divalidasi (422)."""


class CveReferenceOut(BaseModel):
    url: str


class CvePocOut(BaseModel):
    url: str
    source: str = ""
    poc_type: str = "poc"


class CveOut(BaseModel):
    id: int
    cve_id: str
    tech: str = ""
    link: str = ""
    summary: str = ""
    published: str = ""
    reference: list[CveReferenceOut] = []
    affected: list[str] = []
    solutions: str = ""
    cve_score: float = 0.0
    cve_severity: str = ""
    cvss_vector: str = ""
    last_updated: str = ""
    poc_available: bool = False
    pocs: list[CvePocOut] = []
    false_positive: bool = False
    detected_on: str = ""
    news_mentions_count: int = 0
    news_mentions: list[dict[str, str]] = []
    tech_exposure: str = "internal"
    hosting_type: str = "on_prem"
    adjusted_risk_score: float = 0.0
    cisa_kev: bool = False
    active_exploitation: bool = False
    epss_score: float | None = None
    epss_percentile: float | None = None


class CveListResponse(BaseModel):
    cves: list[CveOut]
    total: int
    page: int
    page_size: int


class CveStats(BaseModel):
    total: int
    critical: int
    high: int
    medium: int
    low: int
    unrated: int
    """CVE tanpa skor CVSS (0 / NULL) -- masuk `total`, tapi bukan bucket critical..low."""


class BulkFalsePositiveBody(BaseModel):
    cve_ids: list[CveId]


class PurgeOrphanedBody(BaseModel):
    dry_run: bool = True


class CveTicketBody(BaseModel):
    affected_asset: str = ""
    affected_version: str = ""
    fixed_version: str = ""
    asset_owner: str = ""
    owner_email: str = ""
    owner_team: str = ""
    active_exploitation: str = ""
    remediation_date_plan: str = ""
    remediation_status: str = ""
    actual_remediation_date: str = ""
    escalation_required: bool = False
    comments: str = ""
    risk_acceptance: str = ""
    closure_date: str = ""


class AcknowledgeBody(BaseModel):
    analyst_name: str


class BulkAcknowledgeBody(BaseModel):
    cve_ids: list[CveId]
    analyst_name: str


class DraftEmailBody(BaseModel):
    cve_ids: list[CveId]
    ticket_id: str = ""
