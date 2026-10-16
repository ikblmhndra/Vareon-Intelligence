"""Lockout password buat PUT/DELETE `/api/secrets` dan `POST /api/auth/change-password`
(ROADMAP #23, PR 2).

Kenapa ada: pemegang cookie sesi curian yang menebak password lewat endpoint yang tidak dibatasi
lalu memakainya di endpoint yang dibatasi (konfirmasi perubahan key). Karena itu satu penghitung
Redis (`failures:pw:<user>`, 5 kegagalan per 15 menit) dipakai BERSAMA oleh ganti password dan
halaman key, dan kegagalan ke-5 mencabut semua token user itu: cookie yang dipakai menebak mati,
pemilik sah cukup login ulang. Selama penghitung >= 5, permintaan berikutnya (juga dengan password
yang benar) ditolak 429 sebelum menyentuh user/bcrypt; password benar mereset hitungan.

Dua jebakan tes yang ditangani di sini:
- rate limit biasa PUT/DELETE (5 per menit) ikut habis oleh 5 percobaan gagal, jadi budget-nya
  dikosongkan (`Ctx.reset_write_budget`) sebelum memeriksa lockout, supaya yang menolak lockout;
- pencabutan token membandingkan `iat` dengan `<=` pada resolusi detik: token BARU harus dibuat di
  detik berikutnya (`Ctx.headers_after_revocation`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from cti_core.db.repositories.auth import AsyncUserRepo
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.secrets_router_support import (
    NEW_NVD,
    OLD_NVD,
    PASSWORD,
    PASSWORD_HASH,
    ROOT,
    Ctx,
    open_ctx,
)

pytestmark = pytest.mark.asyncio

LOCKED = "Too many failed password attempts, try again later"
WRONG = "wrong-password-1"


@pytest.fixture
async def ctx(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: Any,
) -> AsyncIterator[Ctx]:
    async with open_ctx(api_client, api_session, auth_header, monkeypatch, fake_redis) as context:
        yield context


def put_request(password: str = PASSWORD) -> tuple[str, str, dict[str, Any]]:
    return (
        "PUT",
        "/api/secrets/nvd",
        {"fields": {"api_key": NEW_NVD}, "current_password": password},
    )


def delete_request(password: str = PASSWORD) -> tuple[str, str, dict[str, Any]]:
    return "DELETE", "/api/secrets/nvd", {"current_password": password}


def change_password_request(password: str = PASSWORD) -> tuple[str, str, dict[str, Any]]:
    return (
        "POST",
        "/api/auth/change-password",
        {"current_password": password, "new_password": "NewP@ssw0rd456"},
    )


WRITES = [pytest.param(put_request, id="put"), pytest.param(delete_request, id="delete")]


async def fail_n_times(
    ctx: Ctx, build: Any, times: int, *, expected: int, headers: dict[str, str] | None = None
) -> list[Response]:
    responses = []
    for _ in range(times):
        resp = await ctx.request(*build(WRONG), headers=headers)
        assert resp.status_code == expected
        responses.append(resp)
    return responses


# --- pencabutan sesi pada kegagalan ke-5 ------------------------------------------------------


@pytest.mark.parametrize("build", WRITES)
async def test_four_wrong_passwords_do_not_revoke_the_session(ctx: Ctx, build: Any) -> None:
    session_token = ctx.auth

    await fail_n_times(ctx, build, 4, expected=403)

    assert await ctx.revoked_at() is None
    assert (await ctx.get(headers=session_token)).status_code == 200


@pytest.mark.parametrize("build", WRITES)
async def test_the_fifth_wrong_password_revokes_every_token_of_the_user(
    ctx: Ctx, build: Any
) -> None:
    session_token = ctx.auth

    await fail_n_times(ctx, build, 5, expected=403)

    assert await ctx.revoked_at() is not None
    assert (await ctx.get(headers=session_token)).status_code == 401


@pytest.mark.parametrize("build", WRITES)
async def test_the_fifth_failure_still_answers_403_with_the_audit_row(ctx: Ctx, build: Any) -> None:
    responses = await fail_n_times(ctx, build, 5, expected=403)

    assert responses[-1].json()["detail"] == "Password confirmation failed"
    assert len(await ctx.audit("secret_reauth_failed")) == 5


# --- terkunci: 429 sebelum menyentuh password -------------------------------------------------


@pytest.mark.parametrize("build", WRITES)
async def test_after_five_failures_even_the_right_password_is_refused_with_429(
    ctx: Ctx, build: Any
) -> None:
    await ctx.seed("nvd")
    await fail_n_times(ctx, build, 5, expected=403)
    fresh = await ctx.headers_after_revocation()
    ctx.reset_write_budget()

    resp = await ctx.request(*build(), headers=fresh)

    assert resp.status_code == 429
    assert resp.json()["detail"] == LOCKED
    assert await ctx.stored("nvd") == {"api_key": OLD_NVD}
    assert ctx.probe.calls == []


@pytest.mark.parametrize("build", WRITES)
async def test_the_lockout_is_per_user(ctx: Ctx, build: Any) -> None:
    await ctx.add_user("second-admin")
    await fail_n_times(ctx, build, 5, expected=403)
    ctx.reset_write_budget()

    resp = await ctx.request(*build(), headers=ctx.headers("second-admin"))

    assert resp.status_code != 429


@pytest.mark.parametrize("build", WRITES)
async def test_a_correct_password_resets_the_failure_count(ctx: Ctx, build: Any) -> None:
    """Empat gagal, satu benar, empat gagal lagi: tanpa reset itu delapan kegagalan beruntun."""
    await ctx.seed("nvd")
    session_token = ctx.auth
    await fail_n_times(ctx, build, 4, expected=403)
    assert (await ctx.request(*build())).status_code == 200
    ctx.reset_write_budget()

    await fail_n_times(ctx, build, 4, expected=403)

    assert await ctx.revoked_at() is None
    assert (await ctx.get(headers=session_token)).status_code == 200


# --- penghitung bersama dengan ganti password -------------------------------------------------


async def test_a_wrong_current_password_on_change_password_is_a_400(ctx: Ctx) -> None:
    resp = await ctx.request(*change_password_request(WRONG))

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Current password is incorrect"


async def test_failures_on_change_password_and_on_secrets_share_one_counter(ctx: Ctx) -> None:
    session_token = ctx.auth

    await fail_n_times(ctx, change_password_request, 3, expected=400)
    await fail_n_times(ctx, put_request, 2, expected=403)

    assert await ctx.revoked_at() is not None
    assert (await ctx.get(headers=session_token)).status_code == 401


async def test_secrets_failures_lock_the_right_password_out_of_change_password(ctx: Ctx) -> None:
    await fail_n_times(ctx, put_request, 5, expected=403)
    fresh = await ctx.headers_after_revocation()

    resp = await ctx.request(*change_password_request(), headers=fresh)

    assert resp.status_code == 429
    assert resp.json()["detail"] == LOCKED


async def test_change_password_is_locked_out_after_five_failures_and_changes_nothing(
    ctx: Ctx,
) -> None:
    await fail_n_times(ctx, change_password_request, 5, expected=400)
    fresh = await ctx.headers_after_revocation()

    resp = await ctx.request(*change_password_request(), headers=fresh)

    assert resp.status_code == 429
    assert resp.json()["detail"] == LOCKED
    user = await AsyncUserRepo(ctx.session).get_by_username(ROOT)
    assert user is not None
    assert user.password_hash == PASSWORD_HASH


async def test_the_fifth_failed_change_password_revokes_the_session(ctx: Ctx) -> None:
    session_token = ctx.auth

    await fail_n_times(ctx, change_password_request, 5, expected=400)

    assert await ctx.revoked_at() is not None
    assert (await ctx.get(headers=session_token)).status_code == 401


# --- password terlalu panjang -----------------------------------------------------------------


@pytest.mark.parametrize("build", WRITES)
async def test_a_password_longer_than_72_bytes_is_a_wrong_password_not_a_server_error(
    ctx: Ctx, build: Any
) -> None:
    """bcrypt menolak > 72 byte dengan ValueError: itu tebakan yang salah, bukan 500."""
    resp = await ctx.request(*build("a" * 100))

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Password confirmation failed"


async def test_a_password_longer_than_72_bytes_is_a_wrong_password_on_change_password(
    ctx: Ctx,
) -> None:
    resp = await ctx.request(*change_password_request("a" * 100))

    assert resp.status_code == 400
