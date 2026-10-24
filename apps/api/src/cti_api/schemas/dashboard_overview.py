"""Skema response `/api/dashboard/{map,attention,trending,ransomware,cve-exposure}`.
Bentuknya mengikuti dict dari `services/dashboard_overview` dan `services/trending`."""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel


class MapPoint(BaseModel):
    country_code: str
    incidents: int
    ransomware_victims: int
    top_actor: str | None = None
    top_industry: str | None = None


class DashboardMap(BaseModel):
    points: list[MapPoint]
    client_countries: list[str]
    generated_at: str


class Brief(BaseModel):
    headline: str
    detail: str


class DashboardAttention(BaseModel):
    kev_in_stack: int
    kev_without_ticket: int
    ransomware_in_client_scope: int
    watchlist_hits: int
    pir_hits: int
    brief: Brief
    generated_at: str


class TrendItemOut(BaseModel):
    kind: Literal["actor", "ttp"]
    name: str
    ttp_id: str | None = None
    count: int
    prev_count: int
    change_pct: int | None = None
    is_new: bool
    daily: list[int]


class TrendingResponse(BaseModel):
    items: list[TrendItemOut]
    window_days: int
    window_label: str
    baseline_reliable: bool = True
    generated_at: str


class WeekCount(BaseModel):
    week_start: datetime.date
    victims: int


class NameCount(BaseModel):
    name: str
    count: int


class RansomwareOverview(BaseModel):
    weekly: list[WeekCount]
    top_groups: list[NameCount]
    total: int
    apac: int
    undated: int
    generated_at: str


class CveExposureItem(BaseModel):
    cve_id: str
    tech: str | None = None
    cvss: float | None = None
    cisa_kev: bool
    ticket_id: str | None = None
    ticket_age_days: int | None = None
    public_poc: bool


class CveExposure(BaseModel):
    items: list[CveExposureItem]
    open_critical: int
    open_kev: int
    closed_in_period: int
    mean_days_to_close: float | None = None
    generated_at: str
