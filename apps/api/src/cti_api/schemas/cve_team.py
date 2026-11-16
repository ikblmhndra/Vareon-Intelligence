"""Skema tim pemilik CVE (`/api/cve/teams`), dipakai dropdown ticket dan draf eskalasi."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, StringConstraints

TeamName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LeadName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class CveTeamIn(BaseModel):
    name: TeamName
    lead_name: LeadName = ""
    lead_email: EmailStr | Literal[""] = ""


class CveTeamPatch(BaseModel):
    """Semua field opsional; yang tidak dikirim tidak diubah. `active=true` mengaktifkan lagi."""

    name: TeamName | None = None
    lead_name: LeadName | None = None
    lead_email: EmailStr | Literal[""] | None = None
    active: bool | None = None


class CveTeamOut(BaseModel):
    id: int
    name: str
    lead_name: str
    lead_email: str
    active: bool
    ticket_count: int


class CveTeamListResponse(BaseModel):
    items: list[CveTeamOut]
    total: int
