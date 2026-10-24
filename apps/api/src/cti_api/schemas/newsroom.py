"""Skema respons newsroom (topik yang sedang naik)."""

from __future__ import annotations

import datetime

from pydantic import BaseModel

from cti_api.schemas.dashboard_overview import TrendItemOut


class TopicArticle(BaseModel):
    id: int
    title: str
    posted_on: datetime.date | None = None


class TopicOut(TrendItemOut):
    top_countries: list[str]
    latest_article: TopicArticle | None = None


class TopicsResponse(BaseModel):
    items: list[TopicOut]
    window_days: int
    window_label: str
    baseline_reliable: bool = True
    generated_at: str
