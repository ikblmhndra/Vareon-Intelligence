"""Pencabutan token JWT lewat Redis (JWT murni stateless tidak bisa dibatalkan).

- `revoke_user_tokens`: semua token user yang diterbitkan sebelum sekarang jadi tidak valid (dipakai
  saat ganti/reset password, ubah role, ubah daftar client).
- `revoke_token`: satu token (logout).
Key kedaluwarsa sendiri begitu token terlama pasti sudah habis, jadi Redis tidak menumpuk."""

from __future__ import annotations

import time
from typing import Any

from cti_core.config import get_settings
from redis.asyncio import Redis

_USER_KEY = "revoked_user:"
_JTI_KEY = "revoked_jti:"


async def revoke_user_tokens(redis: Redis, username: str) -> None:
    ttl = get_settings().auth.jwt_expire_min * 60 + 60
    await redis.set(f"{_USER_KEY}{username}", int(time.time()), ex=ttl)


async def revoke_token(redis: Redis, payload: dict[str, Any]) -> None:
    jti = payload.get("jti")
    if not jti:
        return
    ttl = max(int(payload.get("exp", 0)) - int(time.time()), 1)
    await redis.set(f"{_JTI_KEY}{jti}", 1, ex=ttl)


async def is_revoked(redis: Redis, payload: dict[str, Any]) -> bool:
    user_ts, jti_hit = await redis.mget(
        f"{_USER_KEY}{payload.get('sub', '')}", f"{_JTI_KEY}{payload.get('jti', '')}"
    )
    if jti_hit is not None:
        return True
    return user_ts is not None and int(payload.get("iat", 0)) <= int(user_ts)
