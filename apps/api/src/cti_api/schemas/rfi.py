"""Adaptasi dari `ScraperNewsWeb/app/models/rfi.py` -- `id`/`linked_pir`
sekarang `int` (Postgres bigint), BUKAN `str` (Mongo ObjectId hex)."""

from __future__ import annotations

import datetime

from pydantic import BaseModel


class RFICreate(BaseModel):
    requester: str
    question: str
    due_date: datetime.date | None = None
    status: str = "open"
    linked_pir: int | None = None
    response: str = ""


class RFIUpdate(BaseModel):
    requester: str | None = None
    question: str | None = None
    due_date: datetime.date | None = None
    status: str | None = None
    linked_pir: int | None = None
    response: str | None = None


class RFIOut(BaseModel):
    id: int
    requester: str
    question: str
    due_date: str | None = None
    status: str
    linked_pir: int | None = None
    response: str
    created_at: str
    updated_at: str


class RFIStatusCounts(BaseModel):
    open: int = 0
    in_progress: int = 0
    closed: int = 0


class RFIListResponse(BaseModel):
    rfis: list[RFIOut]
    status_counts: RFIStatusCounts
    total: int
    page: int
    page_size: int
