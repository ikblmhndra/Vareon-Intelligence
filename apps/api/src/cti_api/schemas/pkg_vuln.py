"""Adaptasi dari `ScraperNewsWeb/app/models/pkg_vuln.py`. Fase 7.3
(router `pkg_vuln`, Bagian 4). `epss_score`/`epss_percentile`/`kev`/
`kev_date_added` tetap ada di response (skema faithful) walau SELALU
kosong/`False` sampai `epss_service`/`cisa_kev_service` diport terpisah
-- lihat docstring `cti_core.db.models.package`."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MonitoredPackageOut(BaseModel):
    id: int
    name: str
    ecosystem: str
    version: str | None = None
    client_id: str
    added_date: str
    last_scan: str | None = None
    vuln_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    highest_severity: str
    latest_version: str | None = None
    source: str
    dep_direct_count: int
    dep_indirect_count: int
    dep_total_count: int
    dep_resolved_at: str | None = None
    scorecard_score: float | None = None
    scorecard_date: str | None = None
    source_path: str = ""


class MonitoredPackageAddBody(BaseModel):
    name: str
    ecosystem: str
    version: str | None = None


class MonitoredPackageEditBody(BaseModel):
    version: str | None = None
    ecosystem: str | None = None


class MonitoredPackageListResponse(BaseModel):
    items: list[MonitoredPackageOut]
    total: int
    page: int
    page_size: int


class PackageVulnOut(BaseModel):
    id: int
    package_name: str
    ecosystem: str
    pinned_version: str | None = None
    advisory_id: str
    aliases: list[str] = []
    summary: str = ""
    details: str = ""
    severity: str = "UNKNOWN"
    cvss_score: float | None = None
    epss_score: float | None = None
    epss_percentile: float | None = None
    kev: bool = False
    kev_date_added: str | None = None
    adjusted_score: float | None = None
    adjusted_severity: str | None = None
    published: str | None = None
    modified: str | None = None
    fixed_version: str | None = None
    affected_version_ranges: list[str] = []
    references: list[str] = []
    client_id: str
    acknowledged: bool = False
    ack_by: str | None = None
    ack_date: str | None = None
    source: str = "osv.dev"


class PackageVulnListResponse(BaseModel):
    items: list[PackageVulnOut]
    total: int
    page: int
    page_size: int


class LockfileImportResult(BaseModel):
    parsed: int
    added: int
    skipped: int
    errors: list[str] = []
    packages: list[dict[str, Any]] = []
    dry_run: bool = False
    detected_format: str = ""
    ecosystem: str = ""
    new: int = 0
    already_monitored: int = 0
    version_changes: int = 0
    unsupported: int = 0


class PkgVulnStats(BaseModel):
    packages: int
    total_vulns: int
    critical: int
    high: int
    medium: int
    low: int
    unacknowledged: int
    kev_count: int
    vulnerable_packages: int


class PackageDepGraphOut(BaseModel):
    id: int
    pkg_id: int
    package_name: str
    ecosystem: str
    version: str | None = None
    resolved_at: str
    direct_count: int
    indirect_count: int
    total_count: int
    direct_deps: list[dict[str, Any]] = []
    indirect_deps: list[dict[str, Any]] = []
    scorecard_score: float | None = None
    scorecard_date: str | None = None
    scorecard_project: str | None = None
    scorecard_checks: list[dict[str, Any]] = []
    error: str | None = None
