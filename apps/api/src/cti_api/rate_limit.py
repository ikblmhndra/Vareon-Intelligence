"""Rate limit login -- Redis fixed-window (`INCR` + `EXPIRE`), BUKAN port
langsung dari `ScraperNewsWeb/app/services/rate_limit_service.py` (dict
in-memory per-proses). Sengaja diganti: goal Fase 6/7 eksplisit "API bisa
di-scale horizontal" (uvicorn multi-worker) -- limiter in-memory jadi salah
per-proses (N worker = limit efektif N kali lipat, silent). Redis udah jadi
infra baku platform ini (broker Celery, `TokenBucket` scraper), pola yang
sama dipakai di sini, bukan dependency baru."""

from __future__ import annotations

from functools import lru_cache
from typing import cast

from cti_core.config import get_settings
from fastapi import HTTPException
from redis.asyncio import Redis

from cti_api.token_revocation import revoke_user_tokens


async def is_rate_limited(
    redis: Redis, key: str, *, max_requests: int = 10, window_seconds: int = 60
) -> bool:
    # SET NX EX + INCR dalam satu transaksi: key selalu punya TTL, tidak bisa terkunci permanen
    # kalau proses mati di antara dua perintah.
    name = f"ratelimit:{key}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.set(name, 0, ex=window_seconds, nx=True)
        pipe.incr(name)
        results = await pipe.execute()
    return cast(int, results[-1]) > max_requests


PASSWORD_FAILURE_LIMIT = 5
PASSWORD_FAILURE_WINDOW_S = 900


async def check_password_lockout(redis: Redis, username: str) -> None:
    """429 kalau `username` sudah gagal konfirmasi password >= `PASSWORD_FAILURE_LIMIT` kali dalam
    `PASSWORD_FAILURE_WINDOW_S`. Satu penghitung dipakai SEMUA tempat yang meminta password akun
    yang sedang login (ganti password, ubah key third-party): kalau tidak, pemegang cookie sesi
    curian menebak password lewat endpoint yang tidak dibatasi, lalu memakainya di endpoint yang
    dibatasi."""
    value = await redis.get(f"failures:pw:{username}")
    if value is not None and int(value) >= PASSWORD_FAILURE_LIMIT:
        raise HTTPException(
            status_code=429, detail="Too many failed password attempts, try again later"
        )


async def note_password_failure(redis: Redis, username: str) -> None:
    """Catat satu kegagalan. Begitu batasnya tercapai SEMUA sesi akun itu dicabut: cookie yang
    dipakai menebak mati, dan pemilik sah cukup login ulang dengan password-nya."""
    name = f"failures:pw:{username}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.set(name, 0, ex=PASSWORD_FAILURE_WINDOW_S, nx=True)
        pipe.incr(name)
        results = await pipe.execute()
    if cast(int, results[-1]) >= PASSWORD_FAILURE_LIMIT:
        await revoke_user_tokens(redis, username)


async def clear_password_failures(redis: Redis, username: str) -> None:
    await redis.delete(f"failures:pw:{username}")


@lru_cache(maxsize=1)
def get_redis_client() -> Redis:
    """Lazy + di-cache per-proses -- sama pola `get_settings()`/
    `get_celery_client()` (`cti_core`). Bukan modul-level singleton yang
    konek pas IMPORT: `cti_api.deps` ke-import duluan sebelum test fixture
    sempat nunjuk `REDIS__URL` ke instance testcontainer/lain."""
    return cast(Redis, Redis.from_url(get_settings().redis.url, decode_responses=True))
