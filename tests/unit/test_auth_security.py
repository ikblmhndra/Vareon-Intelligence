"""Unit test `cti_api.security` -- hash password (bcrypt) + JWT
encode/decode. Murni fungsi, gak nyentuh DB/Redis. `create_token`/`decode_token`
manggil `get_settings()` (butuh `AUTH__JWT_SECRET` dkk), dan dulu diam-diam
ngandelin `.env` repo -- lolos di laptop, MERAH di CI/checkout bersih (ketauan
dari simulasi CI Fase 10.D). Sekarang env-nya di-set lewat `monkeypatch`
(function-scope, gak bocor ke test lain -- lihat catatan
`tests/integration/conftest.py`), nilainya nilai uji, bukan secret beneran."""

from __future__ import annotations

import pytest
from cti_api.rate_limit import retry_after_seconds
from cti_api.security import create_token, decode_token, hash_password, verify_password
from cti_core.config import get_settings
from jose import JWTError, jwt


@pytest.fixture(autouse=True)
def _auth_settings(monkeypatch: pytest.MonkeyPatch):
    for key, value in {
        "DATABASE__URL": "postgresql+asyncpg://x:x@localhost/x",
        "DATABASE__SYNC_URL": "postgresql+psycopg://x:x@localhost/x",
        "AUTH__JWT_SECRET": "unit-test-jwt-secret",
        "AUTH__SESSION_SECRET_KEY": "unit-test-session-secret",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_hash_password_roundtrip() -> None:
    hashed = hash_password("Sup3rSecr3t!")
    assert hashed != "Sup3rSecr3t!"
    assert verify_password("Sup3rSecr3t!", hashed)


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("Sup3rSecr3t!")
    assert not verify_password("wrong", hashed)


def test_hash_password_different_salt_each_call() -> None:
    """bcrypt salt acak -- dua hash password sama HARUS beda string,
    kalau sama berarti salt-nya gak jalan (regresi keamanan serius)."""
    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2
    assert verify_password("same-password", h1)
    assert verify_password("same-password", h2)


def test_create_and_decode_token_roundtrip() -> None:
    token = create_token("alice", "analyst", client_ids=["default", "acme"])
    payload = decode_token(token)
    assert payload["sub"] == "alice"
    assert payload["role"] == "analyst"
    assert payload["client_ids"] == ["default", "acme"]


def test_create_token_defaults_client_ids() -> None:
    token = create_token("bob", "admin")
    payload = decode_token(token)
    assert payload["client_ids"] == ["default"]


def test_decode_token_rejects_tampered_token() -> None:
    """Tamper di TENGAH signature, bukan karakter terakhir -- base64url HMAC
    256-bit nyisain 2 bit padding gak signifikan di char terakhir, jadi
    tukar char di posisi itu (mis. "A"<->"B") kadang gak beneran ngubah
    bytes-nya, bikin test ini flaky (ketauan lewat run beneran, bukan
    dugaan)."""
    token = create_token("alice", "analyst")
    mid = len(token) // 2
    tampered = token[:mid] + ("A" if token[mid] != "A" else "B") + token[mid + 1 :]
    with pytest.raises(JWTError):
        decode_token(tampered)


def test_decode_token_rejects_wrong_secret() -> None:
    from cti_core.config import get_settings

    settings = get_settings().auth
    bad_token = jwt.encode(
        {"sub": "eve", "role": "superadmin"}, "wrong-secret", algorithm=settings.jwt_algorithm
    )
    with pytest.raises(JWTError):
        decode_token(bad_token)


@pytest.mark.asyncio
async def test_retry_after_seconds_clamps_ttl() -> None:
    class _Stub:
        def __init__(self, ttl: int) -> None:
            self._ttl = ttl
            self.keys: list[str] = []

        async def ttl(self, key: str) -> int:
            self.keys.append(key)
            return self._ttl

    for ttl, expected in [(-2, 60), (-1, 60), (0, 60), (37, 37), (999, 60)]:
        stub = _Stub(ttl)
        assert await retry_after_seconds(stub, "login:1.2.3.4") == expected  # type: ignore[arg-type]
        assert stub.keys == ["ratelimit:login:1.2.3.4"]
