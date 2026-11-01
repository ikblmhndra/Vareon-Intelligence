"""Skema administrasi token mesin (P7b). `token` hanya ada di respons pembuatan."""

import datetime
from typing import Annotated

from cti_core.indicator.marking import Tlp
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from cti_api.machine_auth import API_TOKEN_SCOPES, DEFAULT_TOKEN_SCOPES


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
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_TOKEN_SCOPES), min_length=1)
    """Subset `API_TOKEN_SCOPES`; disimpan tanpa duplikat, urut abjad."""

    @field_validator("scopes")
    @classmethod
    def _known_scopes(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(API_TOKEN_SCOPES))
        if unknown:
            raise ValueError(f"Unknown scope(s): {', '.join(unknown)}")
        return sorted(set(v))


class ApiTokenCreated(ApiTokenOut):
    token: str
