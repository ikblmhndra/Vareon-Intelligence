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
from redis.asyncio import Redis


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


@lru_cache(maxsize=1)
def get_redis_client() -> Redis:
    """Lazy + di-cache per-proses -- sama pola `get_settings()`/
    `get_celery_client()` (`cti_core`). Bukan modul-level singleton yang
    konek pas IMPORT: `cti_api.deps` ke-import duluan sebelum test fixture
    sempat nunjuk `REDIS__URL` ke instance testcontainer/lain."""
    return cast(Redis, Redis.from_url(get_settings().redis.url, decode_responses=True))
