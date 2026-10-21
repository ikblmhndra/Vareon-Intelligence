"""Adaptasi dari `ScraperNewsWeb/app/routers/filtered_articles.py` (gak
ada Pydantic model terpisah di legacy, dict inline). `id` sekarang `int`
(Postgres), bukan Mongo ObjectId hex."""

from __future__ import annotations

from pydantic import BaseModel


class RejectedArticleOut(BaseModel):
    id: int
    title: str
    url: str
    source: str
    posted_on: str | None = None
    reason: str | None = None
    failure_kind: str | None = None
    """None = ditolak klasifikasi; `transient`/`json`/`permanent` = enrichment GAGAL (replay)."""
    rejected_at: str


class RejectedArticleListResponse(BaseModel):
    items: list[RejectedArticleOut]
    total: int
    page: int
    page_size: int
