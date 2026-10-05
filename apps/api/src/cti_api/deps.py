"""FastAPI dependency injector -- port 1:1 dari `ScraperNewsWeb/app/auth.py`.
Untuk JWT encode/decode lihat `security.py`; untuk OIDC/SSO (Fase 7 lanjutan,
`oidc.enabled` masih `False` default) belum diport."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypedDict

from cti_core.db.engine import get_async_session
from fastapi import Depends, Header, HTTPException, Request
from jose import JWTError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.rate_limit import get_redis_client
from cti_api.security import decode_token

__all__ = [
    "AuthedUser",
    "effective_client_id",
    "ensure_client_access",
    "get_current_user",
    "get_db",
    "get_redis",
    "request_ip",
    "require_admin",
    "require_auth",
    "require_superadmin",
]


class AuthedUser(TypedDict):
    username: str
    role: str
    client_ids: list[str]


async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in get_async_session():
        yield session


async def get_redis() -> Redis:
    return get_redis_client()


async def get_current_user(authorization: str | None = Header(None)) -> AuthedUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    try:
        payload: dict[str, Any] = decode_token(token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    raw = payload.get("client_ids")
    client_ids = raw if isinstance(raw, list) and raw else [payload.get("client_id", "default")]
    username = payload.get("sub")
    if not isinstance(username, str) or not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return AuthedUser(
        username=username,
        role=payload.get("role", "analyst"),
        client_ids=client_ids,
    )


async def require_auth(user: AuthedUser = Depends(get_current_user)) -> AuthedUser:
    return user


async def require_admin(user: AuthedUser = Depends(get_current_user)) -> AuthedUser:
    if user["role"] not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


async def require_superadmin(user: AuthedUser = Depends(get_current_user)) -> AuthedUser:
    if user["role"] != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin role required")
    return user


def effective_client_id(user: AuthedUser, x_client_id: str | None) -> str:
    """client_id aktif buat request ini. Superadmin: header apa pun
    diterima. Selain itu: header cuma dipakai kalau ada di `client_ids`
    user, else fallback ke client pertama user."""
    client_ids = user.get("client_ids", ["default"])
    if not x_client_id:
        return client_ids[0] if client_ids else "default"
    if user["role"] == "superadmin":
        return x_client_id
    return x_client_id if x_client_id in client_ids else client_ids[0]


def ensure_client_access(user: AuthedUser, client_id: str) -> None:
    """Tolak (404, bukan 403: tidak membocorkan keberadaan) akses ke objek milik client lain."""
    if user["role"] == "superadmin":
        return
    if client_id not in user.get("client_ids", []):
        raise HTTPException(status_code=404, detail="Not found")


def request_ip(request: Request) -> str:
    return request.client.host if request.client else ""
