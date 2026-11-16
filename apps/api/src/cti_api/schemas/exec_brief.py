"""Skema brief eksekutif bersama (satu dokumen per tanggal untuk seluruh platform)."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict


class ExecBriefFilters(BaseModel):
    days: int
    incident_only: bool
    confirmed_only: bool


class ExecBriefOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    brief_date: datetime.date
    markdown: str
    filters: ExecBriefFilters
    is_default_filters: bool
    generated_at: datetime.datetime
    generated_by: str
    model: str
    prompt_version: str | None


class ExecBriefRead(BaseModel):
    today: datetime.date
    brief: ExecBriefOut | None


class ExecBriefDates(BaseModel):
    today: datetime.date
    dates: list[datetime.date]
