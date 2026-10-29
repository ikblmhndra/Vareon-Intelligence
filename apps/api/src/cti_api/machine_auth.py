"""Autentikasi mesin (P7b): token API berscope untuk feed REST/TAXII. Sengaja tanpa JWT dan tanpa
Redis supaya feed tetap jalan saat Redis mati; pencabutan berlaku di request berikutnya karena
setiap request mencari baris token di Postgres. Hanya sha256 token yang disimpan."""

import base64
import binascii
import datetime
import hashlib
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from cti_core.db.models import ApiToken
from cti_core.db.repositories.auth import AsyncApiTokenRepo
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import get_db

# Hanya untuk dokumentasi OpenAPI (skema `apiToken`); token dibaca dari header `Authorization`.
_openapi_scheme = HTTPBearer(scheme_name="apiToken", auto_error=False)

API_TOKEN_SCOPES: tuple[str, ...] = ("indicators:read",)
TOKEN_PREFIX = "vrn_"


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_status(
    token: ApiToken, now: datetime.datetime
) -> Literal["active", "expired", "revoked"]:
    if token.revoked_at is not None:
        return "revoked"
    if token.expires_at is not None and token.expires_at <= now:
        return "expired"
    return "active"


@dataclass(frozen=True)
class MachinePrincipal:
    token_id: int
    name: str
    scopes: tuple[str, ...]
    max_tlp: str


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Invalid or missing API token",
        headers={"WWW-Authenticate": 'Basic realm="vareon", Bearer'},
    )


def _extract_token(authorization: str | None) -> str:
    """Token dari `Bearer <t>` atau `Basic base64(user:<t>)`; yang lain -> 401."""
    if not authorization:
        raise _unauthorized()
    scheme, _, value = authorization.partition(" ")
    scheme = scheme.lower()
    if scheme == "bearer":
        token = value
    elif scheme == "basic":
        try:
            decoded = base64.b64decode(value, validate=True).decode()
        except (binascii.Error, UnicodeDecodeError):
            raise _unauthorized() from None
        _, sep, token = decoded.partition(":")
        if not sep:
            raise _unauthorized()
    else:
        raise _unauthorized()
    if not token or token != token.strip() or not token.startswith(TOKEN_PREFIX):
        raise _unauthorized()
    return token


def require_token(scope: str) -> Callable[..., Awaitable[MachinePrincipal]]:
    """Dependency: request harus membawa token aktif yang punya `scope`. `.scope` di fungsi hasil
    dibaca test cakupan route, seperti `.permission` pada `require_permission`."""
    if scope not in API_TOKEN_SCOPES:
        raise ValueError(f"Unknown token scope {scope!r}")

    async def dependency(
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(get_db),
        _scheme: object = Depends(_openapi_scheme),
    ) -> MachinePrincipal:
        token = _extract_token(authorization)
        repo = AsyncApiTokenRepo(session)
        row = await repo.get_by_hash(hash_token(token))
        # Satu pesan untuk tidak dikenal/dicabut/kedaluwarsa: tidak membocorkan keberadaan token.
        if row is None or token_status(row, datetime.datetime.now(datetime.UTC)) != "active":
            raise _unauthorized()
        if scope not in row.scopes:
            raise HTTPException(status_code=403, detail=f"Token lacks scope: {scope}")
        await repo.touch_last_used(row.id)
        await session.commit()
        return MachinePrincipal(row.id, row.name, tuple(row.scopes), row.max_tlp)

    dependency.scope = scope  # type: ignore[attr-defined]
    dependency.__name__ = f"require_token_{scope}"
    return dependency
