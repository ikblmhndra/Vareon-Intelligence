"""Adaptasi dari `ScraperNewsWeb/app/models/pir.py` -- `id` sekarang `int`
(Postgres bigint), BUKAN `str` (Mongo ObjectId hex). `criteria.ttps` di
model lama list of TTP id string -- port apa adanya (bukan objek
{id,name}, beda dari `PIROptions.ttps`/`ArticleOut.ttps` yang emang perlu
nama buat ditampilkan)."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict, Field

from cti_api.schemas.article import TTP


class PIRCriteria(BaseModel):
    threat_actors: list[str] = []
    malware: list[str] = []
    industries: list[str] = []
    countries: list[str] = []
    news_types: list[str] = []
    keywords: list[str] = []
    ttps: list[str] = []


class PIRPreviewCriteria(PIRCriteria):
    """Kriteria untuk pratinjau: kunci asing ditolak (422) supaya typo tidak diam-diam jadi
    hitungan tanpa filter. `PIRCriteria` bersama tetap longgar agar POST/PUT menerima payload
    lama."""

    model_config = ConfigDict(extra="forbid")


class PIRPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: PIRPreviewCriteria
    days: int = Field(90, ge=1, le=365)


class PIRPreviewOut(BaseModel):
    count: int
    days: int
    since: datetime.date
    has_criteria: bool


class PIRCreate(BaseModel):
    title: str
    description: str = ""
    priority: str = "P2"
    owner: str = ""
    criteria: PIRCriteria = PIRCriteria()
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None


class PIRUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    owner: str | None = None
    status: str | None = None
    criteria: PIRCriteria | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None


class PIRNoteIn(BaseModel):
    url: str
    note: str
    analyst: str = ""


class PIROut(BaseModel):
    id: int
    title: str
    description: str
    priority: str
    owner: str
    status: str
    criteria: PIRCriteria
    start_date: str | None = None
    end_date: str | None = None
    coverage_count: int
    recent_coverage: int
    is_gap: bool
    last_match: str | None = None
    created_at: str
    updated_at: str


class PIRArticleOut(BaseModel):
    id: int
    title: str
    url: str
    posted_on: str | None = None
    source: str
    news_type: str | None = None
    threat_actors: list[str] = []
    impacted_industries: list[str] = []
    mentioned_countries: list[str] = []
    has_note: bool = False


class PIRArticleListResponse(BaseModel):
    articles: list[PIRArticleOut]
    total: int
    page: int
    page_size: int


class PIRNoteOut(BaseModel):
    pir_id: int
    url: str
    note: str
    analyst: str
    updated_at: str = ""


class PIRWeekCount(BaseModel):
    week_start: str
    count: int


class PIRWeeklyCoverage(BaseModel):
    pir_id: int
    since: str | None = None
    until: str | None = None
    weeks: list[PIRWeekCount]


class PIROptions(BaseModel):
    threat_actors: list[str]
    malware: list[str]
    industries: list[str]
    countries: list[str]
    news_types: list[str]
    ttps: list[TTP]
