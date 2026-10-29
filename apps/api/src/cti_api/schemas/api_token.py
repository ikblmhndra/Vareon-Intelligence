"""Skema administrasi token mesin (P7b). `token` hanya ada di respons pembuatan."""

import datetime
from typing import Annotated

from cti_core.indicator.marking import Tlp
from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class ApiTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    token_prefix: str
    scopes: list[str]
    max_tlp: str
    created_by: str
    created_at: datetime.datetime
    expires_at: datetime.datetime | None
    last_used_at: datetime.datetime | None
    revoked_at: datetime.datetime | None
    revoked_by: str | None
    status: str


class ApiTokenCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    max_tlp: Tlp = "clear"
    expires_in_days: int | None = Field(default=365, ge=1, le=3650)


class ApiTokenCreated(ApiTokenOut):
    token: str
