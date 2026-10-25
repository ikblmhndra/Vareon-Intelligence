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
    credibility_code: str = Field(..., pattern="^[1-6]$")
    notes: str = Field("", max_length=500)


class SREntryUpdate(BaseModel):
    analyst_name: str = Field(..., min_length=1, max_length=100)
    reliability_grade: str = Field(..., pattern="^[A-Fa-f]$")
    credibility_code: str = Field(..., pattern="^[1-6]$")
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


class SREntryListResponse(BaseModel):
    entries: list[SREntryOut]
    total: int
    page: int
    page_size: int
