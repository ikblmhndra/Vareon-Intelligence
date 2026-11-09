"""Hasil lookup langsung satu CVE (`GET /api/cve/lookup/{cve_id}`, `services/cve_live_lookup.py`).

Bentuknya gabungan beberapa sumber publik; `tracked`/`tracker_tech`/`false_positive` khusus client
pemanggil (tidak pernah ikut cache)."""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, Field


class KevInfo(BaseModel):
    added: datetime.date | None = None
    due: datetime.date | None = None
    action: str = ""


class ExploitHit(BaseModel):
    title: str
    url: str
    published: str = ""


LookupSourceId = Literal["mirror", "nvd", "circl", "exploitdb", "epss"]
LookupSourceStatus = Literal["ok", "not_found", "error", "timeout", "rate_limited", "cached"]


class LookupSource(BaseModel):
    id: LookupSourceId
    status: LookupSourceStatus
    fetched_at: datetime.datetime | None = None


class CveLookupOut(BaseModel):
    cve_id: str
    tracked: bool = False
    tracker_tech: str | None = None
    false_positive: bool = False
    in_mirror: bool = False
    summary: str = ""
    published: datetime.date | None = None
    modified: datetime.datetime | None = None
    cvss_score: float | None = None
    cvss_severity: str | None = None
    cvss_vector: str | None = None
    cwe: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    affected: list[str] = Field(default_factory=list)
    kev: KevInfo | None = None
    epss_score: float | None = None
    epss_percentile: float | None = None
    exploits: list[ExploitHit] = Field(default_factory=list)
    sources: list[LookupSource] = Field(default_factory=list)
