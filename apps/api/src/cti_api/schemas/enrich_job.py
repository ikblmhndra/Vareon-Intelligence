"""Skema antrean kerja LLM (`/api/enrich-jobs`, P7g)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class EnrichJobOut(BaseModel):
    id: int
    kind: Literal["classify", "ttp"]
    url: str
    title: str
    source: str
    posted_on: str | None = None
    state: Literal["pending", "failed"]
    attempts: int
    """Percobaan yang gagal di gateway (tanpa batas)."""
    last_error: str | None = None
    created_at: str
    next_attempt_at: str
    p_threat_news: float | None = None
    """p(threat_news) model relevansi dari `context["relevance"]`; `None` bila tidak ada."""


class EnrichJobListResponse(BaseModel):
    items: list[EnrichJobOut]
    total: int
    page: int
    page_size: int
