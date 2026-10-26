"""Adaptasi dari model Pydantic inline `ScraperNewsWeb/app/routers/
source_reliability.py` -- dipisah ke file `schemas/` sendiri, ikut
konvensi baru (bukan keputusan baru soal validasi/field, cuma lokasi
file)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SREntryAdd(BaseModel):
    source_name: str = Field(..., min_length=1, max_length=200)
    analyst_name: str = Field(..., min_length=1, max_length=100)
    reliability_grade: str = Field(..., pattern="^[A-Fa-f]$")
    credibility_code: str | None = Field(None, pattern="^[1-6]$")
    """P6: opsional, kredibilitas dihitung per artikel; tanpa nilai repo menulis `6`."""
    notes: str = Field("", max_length=500)


class SREntryUpdate(BaseModel):
    analyst_name: str = Field(..., min_length=1, max_length=100)
    reliability_grade: str = Field(..., pattern="^[A-Fa-f]$")
    credibility_code: str | None = Field(None, pattern="^[1-6]$")
    """P6: opsional; tanpa nilai kode tersimpan dipertahankan."""
    notes: str = Field("", max_length=500)


class SREntryOut(BaseModel):
    id: int
    source_name: str
    analyst_name: str
    reliability_grade: str
    credibility_code: str
    admiralty_code: str
    notes: str
    added_date: str
    last_updated: str
    origin: Literal["default", "analyst"]
    content_kind: str | None = None


class SREntryListResponse(BaseModel):
    entries: list[SREntryOut]
    total: int
    page: int
    page_size: int


class SRConfirmIn(BaseModel):
    reliability_grade: str | None = Field(None, pattern="^[A-Fa-f]$")


class SRReviewItem(BaseModel):
    """Satu baris antrean review grade sumber (P6 spec 5.3), statistik 30 hari."""

    entry: SREntryOut
    articles: int
    rejected: int
    artefact_articles: int
    multi_source_stories: int
    lead_count: int
    ioc_verdicts: int
    ioc_fp: int
    rejected_pct: float
    artefact_pct: float
    ioc_fp_pct: float
    suggested_grade: str | None
    suggestion_reasons: list[str]


class SRReviewResponse(BaseModel):
    items: list[SRReviewItem]
