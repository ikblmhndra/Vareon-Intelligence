"""Port 1:1 dari `ScraperNewsWeb/app/models/auth.py`."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    client_ids: list[str] = ["default"]
    client_countries: list[str] = []
    force_pw_change: bool = False
    permissions: list[str] = []


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=1)
    role: str = Field("analyst", max_length=40)
    client_ids: list[str] = Field(default_factory=lambda: ["default"])


class UserClientsUpdate(BaseModel):
    client_ids: list[str] = Field(..., min_length=1)


class UserRoleUpdate(BaseModel):
    role: str = Field(..., max_length=40)


class PasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1)


class PolicySettings(BaseModel):
    min_length: int = Field(8, ge=4, le=128)
    require_upper: bool = True
    require_lower: bool = True
    require_number: bool = True
    require_symbol: bool = True
    force_all_change: bool = False


class UserOut(BaseModel):
    username: str
    role: str
    client_ids: list[str]
    created_at: str
    created_by: str
