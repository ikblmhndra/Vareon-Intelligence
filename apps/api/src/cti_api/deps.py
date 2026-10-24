"""FastAPI dependency injector -- port 1:1 dari `ScraperNewsWeb/app/auth.py`.
Untuk JWT encode/decode lihat `security.py`; untuk OIDC/SSO (Fase 7 lanjutan,
`oidc.enabled` masih `False` default) belum diport."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypedDict

from cti_core.db.engine import get_async_session
from cti_core.db.repositories.auth import AsyncRoleRepo
from fastapi import Depends, Header, HTTPException, Request
from jose import JWTError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.rate_limit import get_redis_client
from cti_api.security import decode_token
from cti_api.token_revocation import is_revoked

__all__ = [
    "AuthedUser",
    "effective_client_id",
    "ensure_client_access",
    "get_current_user",
    "get_db",
    "get_redis",
    "invalidate_role_permissions",
    "permissions_for",
    "request_ip",
    "require_admin",
    "require_auth",
    "require_permission",
    "require_superadmin",
]


class AuthedUser(TypedDict):
    username: str
    role: str
    client_ids: list[str]
    force_pw_change: bool


# Selama `force_pw_change`, hanya endpoint ini yang boleh dipanggil.
_ALLOWED_WHILE_FORCED = {
    "/api/auth/change-password",
    "/api/auth/me",
    "/api/auth/logout",
    "/api/auth/policy",
}


async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in get_async_session():
        yield session


async def get_redis() -> Redis:
    return get_redis_client()


async def get_current_user(
    request: Request,
    authorization: str | None = Header(None),
    redis: Redis = Depends(get_redis),
) -> AuthedUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    try:
        payload: dict[str, Any] = decode_token(token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    if await is_revoked(redis, payload):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    force_pw_change = bool(payload.get("fpc", False))
    if force_pw_change and request.url.path not in _ALLOWED_WHILE_FORCED:
        raise HTTPException(status_code=403, detail="Password change required")
    raw = payload.get("client_ids")
    client_ids = raw if isinstance(raw, list) and raw else [payload.get("client_id", "default")]
    username = payload.get("sub")
    if not isinstance(username, str) or not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return AuthedUser(
        username=username,
        role=payload.get("role", "analyst"),
        client_ids=client_ids,
        force_pw_change=force_pw_change,
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


_ROLE_PERMISSIONS_TTL_S = 30.0
_role_permissions_cache: dict[str, tuple[frozenset[str], float]] = {}


def invalidate_role_permissions(role: str | None = None) -> None:
    """Dipanggil router `roles` sesudah role dibuat/dihapus. Proses uvicorn lain tetap memakai
    cache-nya sampai `_ROLE_PERMISSIONS_TTL_S` habis."""
    if role is None:
        _role_permissions_cache.clear()
    else:
        _role_permissions_cache.pop(role, None)


async def _role_permissions(session: AsyncSession, role: str) -> frozenset[str]:
    now = time.monotonic()
    cached = _role_permissions_cache.get(role)
    if cached is not None and now - cached[1] < _ROLE_PERMISSIONS_TTL_S:
        return cached[0]
    row = await AsyncRoleRepo(session).get(role)
    if row is not None:
        perms = frozenset(row.permissions or [])
    else:
        # Role sistem yang barisnya belum ada (lifespan belum `ensure_system_roles`): definisi kode.
        from cti_api.services.roles import SYSTEM_ROLES

        spec = SYSTEM_ROLES.get(role, {}).get("permissions", [])
        perms = frozenset(spec if isinstance(spec, list) else [])
    _role_permissions_cache[role] = (perms, now)
    return perms


async def permissions_for(session: AsyncSession, role: str) -> list[str]:
    """Permission efektif sebuah role, urut katalog. Dikirim `/api/auth/me` dan login supaya web
    bisa menyembunyikan tombol yang akan dibalas 403 (aturan yang sama dengan `require_permission`:
    superadmin = semua)."""
    from cti_api.services.roles import ALL_PERMISSIONS

    if role == "superadmin":
        return list(ALL_PERMISSIONS)
    granted = await _role_permissions(session, role)
    return [p for p in ALL_PERMISSIONS if p in granted]


def require_permission(permission: str) -> Callable[..., Awaitable[AuthedUser]]:
    """Dependency: user harus punya `permission` lewat role-nya (tabel `roles`). Superadmin lolos
    tanpa lookup. Sebelum ini 26 permission disimpan di role tapi tidak satu router pun yang
    mengeceknya; gating hanya `require_auth`/`require_admin`/`require_superadmin` (audit keamanan
    2026-10-24). `.permission` di fungsi hasil dibaca test cakupan
    (`tests/unit/test_route_permissions.py`) supaya route baru tidak lolos tanpa permission."""
    from cti_api.services.roles import ALL_PERMISSIONS

    if permission not in ALL_PERMISSIONS:
        raise ValueError(f"Unknown permission {permission!r}")

    async def dependency(
        user: AuthedUser = Depends(get_current_user),
        session: AsyncSession = Depends(get_db),
    ) -> AuthedUser:
        if user["role"] == "superadmin":
            return user
        if permission not in await _role_permissions(session, user["role"]):
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
        return user

    dependency.permission = permission  # type: ignore[attr-defined]
    dependency.__name__ = f"require_permission_{permission}"
    return dependency


def effective_client_id(user: AuthedUser, x_client_id: str | None) -> str:
    """client_id aktif buat request ini. Tanpa header: client pertama user. Superadmin: header apa
    pun diterima. Selain itu header yang bukan client user ditolak 403; dulu diam-diam jatuh ke
    client pertama, sehingga salah konfigurasi (atau percobaan membaca client lain) tidak pernah
    terlihat dan data yang tampil bukan milik client yang diminta (audit keamanan 2026-10-24)."""
    client_ids = user.get("client_ids", ["default"])
    if not x_client_id:
        return client_ids[0] if client_ids else "default"
    if user["role"] == "superadmin" or x_client_id in client_ids:
        return x_client_id
    raise HTTPException(status_code=403, detail="Client not assigned to this user")


def ensure_client_access(user: AuthedUser, client_id: str) -> None:
    """Tolak (404, bukan 403: tidak membocorkan keberadaan) akses ke objek milik client lain."""
    if user["role"] == "superadmin":
        return
    if client_id not in user.get("client_ids", []):
        raise HTTPException(status_code=404, detail="Not found")


def request_ip(request: Request) -> str:
    return request.client.host if request.client else ""
