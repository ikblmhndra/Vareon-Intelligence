"""Halaman admin "Third-party keys" (ROADMAP #23): kelola key vendor tanpa restart.

SEMUA endpoint superadmin-only. Router tipis: batas laju, pemanggilan service, lalu commit dan
`overlay.invalidate()` supaya proses ini langsung memakai key baru (proses lain menyusul paling
lambat `overlay.TTL_SECONDS`). Penjelasan aturan (re-auth password, probe sebelum simpan, paket
`llm`, nilai secret tidak pernah keluar) ada di `services/runtime_secrets.py`.

Batas laju per user: 5 tulis/hapus per menit (setiap percobaan menyentuh bcrypt dan, kalau lolos,
vendor luar) dan 10 tes per menit, ditambah cooldown 30 detik per provider untuk tiga provider
berkuota harian (tiap tes memakai satu lookup dari kuota itu). Kegagalan password dihitung terpisah
dan bersama endpoint ganti password (lihat `rate_limit.check_password_lockout`).
"""

from __future__ import annotations

from cti_core.runtime_secrets import overlay
from fastapi import APIRouter, Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, get_db, get_redis, request_ip, require_superadmin
from cti_api.rate_limit import is_rate_limited
from cti_api.schemas.secrets import (
    SecretClearBody,
    SecretProviderOut,
    SecretSetBody,
    SecretsStatusOut,
    SecretTestOut,
)
from cti_api.services import runtime_secrets as service

router = APIRouter(prefix="/api/secrets", tags=["secrets"])

_WRITE_LIMIT = 5
_TEST_LIMIT = 10
_QUOTA_BOUND = frozenset({"abuseipdb", "virustotal", "otx"})
_TEST_COOLDOWN_S = 30

# Kontrak galat selain 200/422-validasi; supaya OpenAPI (dan klien yang di-generate) tahu bentuknya.
_ERRORS: dict[int | str, dict[str, str]] = {
    403: {"description": "Not a superadmin, wrong password, or the account has no local password"},
    404: {"description": "Unknown provider, or no override to clear"},
    409: {"description": "The stored override cannot be read (master key changed); clear it first"},
    422: {
        "description": "Invalid field, or the probe failed and nothing was saved. `detail` is a "
        "string, or an object `{message, probe: {status, detail}}` for a failed probe"
    },
    429: {"description": "Rate limit, test cooldown, or too many failed password attempts"},
    503: {"description": "SECRETS_ENCRYPTION_KEYS is not configured on the server"},
}


async def _limit(redis: Redis, kind: str, username: str, max_requests: int) -> None:
    if await is_rate_limited(redis, f"secrets:{kind}:{username}", max_requests=max_requests):
        raise HTTPException(status_code=429, detail="Too many requests, try again in a minute")


@router.get("", response_model=SecretsStatusOut)
async def get_secrets(
    session: AsyncSession = Depends(get_db), _admin: AuthedUser = Depends(require_superadmin)
) -> SecretsStatusOut:
    return await service.get_status(session)


@router.put("/{provider}", response_model=SecretProviderOut, responses=_ERRORS)
async def put_secret(
    provider: str,
    body: SecretSetBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    admin: AuthedUser = Depends(require_superadmin),
) -> SecretProviderOut:
    await _limit(redis, "write", admin["username"], _WRITE_LIMIT)
    out = await service.set_fields(
        session,
        redis,
        user=admin,
        provider=provider,
        fields=body.fields,
        password=body.current_password,
        ip=request_ip(request),
    )
    await session.commit()
    overlay.invalidate()
    return out


@router.delete("/{provider}", response_model=SecretProviderOut, responses=_ERRORS)
async def delete_secret(
    provider: str,
    body: SecretClearBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    admin: AuthedUser = Depends(require_superadmin),
) -> SecretProviderOut:
    await _limit(redis, "write", admin["username"], _WRITE_LIMIT)
    out = await service.clear_provider(
        session,
        redis,
        user=admin,
        provider=provider,
        password=body.current_password,
        ip=request_ip(request),
    )
    await session.commit()
    overlay.invalidate()
    return out


@router.post("/{provider}/test", response_model=SecretTestOut, responses=_ERRORS)
async def test_secret(
    provider: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    admin: AuthedUser = Depends(require_superadmin),
) -> SecretTestOut:
    await _limit(redis, "test", admin["username"], _TEST_LIMIT)
    if provider in _QUOTA_BOUND and await is_rate_limited(
        redis, f"secrets:cooldown:{provider}", max_requests=1, window_seconds=_TEST_COOLDOWN_S
    ):
        raise HTTPException(
            status_code=429,
            detail=f"This provider was tested moments ago; wait {_TEST_COOLDOWN_S} seconds",
        )
    out = await service.probe_provider(
        session, user=admin, provider=provider, ip=request_ip(request)
    )
    await session.commit()
    return out
