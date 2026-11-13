"""Snapshot test `routers/auth.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`).

`POST /login` butuh rate-limit Redis (`is_rate_limited`) -- `api_client`
(`conftest.py`) udah override `get_redis` numpang `_FakeRedis` in-memory
buat SEMUA test, gak butuh Redis server beneran. System roles
(`ensure_system_roles`, biasanya lifespan yang jalanin) di-seed manual
di sini karena lifespan `create_app()` sengaja gak jalan lewat
`ASGITransport` (lihat docstring `api_client`)."""

from __future__ import annotations

import asyncio
import datetime
import time
from collections.abc import Callable
from typing import Any

import pytest
from cti_api.security import decode_token, hash_password
from cti_api.services.roles import ensure_system_roles
from cti_core.db.repositories.auth import AsyncClientRepo, AsyncUserRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_PASSWORD = "P@ssw0rd123"

_NORMALIZE = path_type(
    {
        r"(.*\.)?access_token$": (str,),
        r"(.*\.)?created_at$": (str,),
        r"(.*\.)?last_sign_in$": (str,),
        r"(.*\.)?signed_in_at$": (str,),
        r"(.*\.)?timestamp$": (str,),
    },
    regex=True,
    strict=False,
)


async def _seed_user(
    session: AsyncSession, *, username: str = "analyst1", role: str = "analyst"
) -> None:
    await ensure_system_roles(session)
    await AsyncUserRepo(session).create(
        username=username,
        password_hash=hash_password(_PASSWORD),
        role_name=role,
        client_ids=["default"],
    )


async def test_get_pw_policy(
    api_client: AsyncClient, api_session: AsyncSession, snapshot: SnapshotAssertion
) -> None:
    resp = await api_client.get("/api/auth/policy")
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_update_pw_policy(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.put(
        "/api/auth/policy",
        headers=auth_header(role="admin"),
        json={
            "min_length": 10,
            "require_upper": True,
            "require_lower": True,
            "require_number": True,
            "require_symbol": False,
            "force_all_change": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_login_success(
    api_client: AsyncClient, api_session: AsyncSession, snapshot: SnapshotAssertion
) -> None:
    await _seed_user(api_session)
    resp = await api_client.post(
        "/api/auth/login", json={"username": "analyst1", "password": _PASSWORD}
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_login_invalid_credentials(
    api_client: AsyncClient, api_session: AsyncSession, snapshot: SnapshotAssertion
) -> None:
    await _seed_user(api_session)
    resp = await api_client.post(
        "/api/auth/login", json={"username": "analyst1", "password": "wrong"}
    )
    assert resp.status_code == 401
    assert resp.json() == snapshot


async def test_login_rate_limited_sends_retry_after(
    api_client: AsyncClient, api_session: AsyncSession
) -> None:
    await _seed_user(api_session)
    first_ten = [
        await api_client.post("/api/auth/login", json={"username": "analyst1", "password": "wrong"})
        for _ in range(10)
    ]
    assert [r.status_code for r in first_ten] == [401] * 10
    resp = await api_client.post(
        "/api/auth/login", json={"username": "analyst1", "password": "wrong"}
    )
    assert resp.status_code == 429
    assert resp.headers["Retry-After"].isdigit()
    assert 1 <= int(resp.headers["Retry-After"]) <= 60
    assert resp.json()["detail"] == "Too many login attempts. Try again in a minute."


async def test_logout(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.post("/api/auth/logout", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_change_password(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_user(api_session)
    resp = await api_client.post(
        "/api/auth/change-password",
        headers=auth_header(username="analyst1"),
        json={"current_password": _PASSWORD, "new_password": "NewP@ssw0rd456"},
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_init_admin(
    api_client: AsyncClient, api_session: AsyncSession, snapshot: SnapshotAssertion
) -> None:
    await ensure_system_roles(api_session)
    resp = await api_client.post(
        "/api/auth/init", json={"username": "bootstrap-admin", "password": _PASSWORD}
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_me(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/auth/me", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_me_signed_in_at_matches_token_iat(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    headers = auth_header()
    iat = decode_token(headers["Authorization"].split(" ", 1)[1])["iat"]
    resp = await api_client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert datetime.datetime.fromisoformat(body["signed_in_at"]) == datetime.datetime.fromtimestamp(
        iat, datetime.UTC
    )
    assert body["signed_in_at"].endswith("+00:00")


async def test_me_multiple_clients(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regresi 2026-10-24: `/me` dulu `asyncio.gather` beberapa `client_repo.get()` di SATU
    `AsyncSession` -- user dengan >1 client kadang dapat 500 (`InvalidRequestError: ...
    concurrent operations are not permitted`) dan AuthProvider web nge-logout dia. Sekarang
    dimuat berurutan; urutan + isi `clients_map` dan `client_countries` (client pertama) harus
    tetap sama.

    Race aslinya gak bisa direproduksi di sini (`api_session` udah pegang koneksi, jadi gak ada
    fase "provisioning a new connection"), makanya `execute` dibungkus penghitung query yang
    lagi jalan barengan: lebih dari 1 = masih ada operasi konkuren di satu session."""
    await AsyncClientRepo(api_session).create(client_id="acme", name="Acme", countries=["SG"])

    in_flight = max_in_flight = 0
    original_execute = api_session.execute

    async def _counting_execute(*args: Any, **kwargs: Any) -> Any:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        try:
            await asyncio.sleep(0)  # kasih kesempatan coroutine lain nyalip kalau di-gather
            return await original_execute(*args, **kwargs)
        finally:
            in_flight -= 1

    monkeypatch.setattr(api_session, "execute", _counting_execute)
    resp = await api_client.get("/api/auth/me", headers=auth_header(client_ids=["acme", "default"]))
    assert resp.status_code == 200
    assert max_in_flight == 1
    body = resp.json()
    assert set(body["clients_map"]) == {"acme", "default"}
    assert body["clients_map"]["acme"] == ["SG"]
    assert body["client_countries"] == ["SG"]


async def test_get_users(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_user(api_session)
    resp = await api_client.get("/api/auth/users", headers=auth_header(role="admin"))
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_add_user(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await ensure_system_roles(api_session)
    resp = await api_client.post(
        "/api/auth/users",
        headers=auth_header(role="admin"),
        json={
            "username": "newanalyst",
            "password": _PASSWORD,
            "role": "analyst",
            "client_ids": ["default"],
        },
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_reset_user_password(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_user(api_session)
    resp = await api_client.post(
        "/api/auth/users/analyst1/reset-password",
        headers=auth_header(role="admin"),
        json={"new_password": "NewP@ssw0rd456"},
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot
    # reset admin menandai akun: admin tahu password yang diketiknya (D4)
    login = await api_client.post(
        "/api/auth/login", json={"username": "analyst1", "password": "NewP@ssw0rd456"}
    )
    assert login.status_code == 200
    assert login.json()["force_pw_change"] is True


async def _reset_then_login(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    fake_redis: Any,
    api_session: AsyncSession,
) -> str:
    await _seed_user(api_session)
    resp = await api_client.post(
        "/api/auth/users/analyst1/reset-password",
        headers=auth_header(role="admin"),
        json={"new_password": "NewP@ssw0rd456"},
    )
    assert resp.status_code == 200
    # reset mencabut token user di detik yang sama; mundurkan agar login berikutnya tidak ikut
    await fake_redis.set("revoked_user:analyst1", int(time.time()) - 5)
    login = await api_client.post(
        "/api/auth/login", json={"username": "analyst1", "password": "NewP@ssw0rd456"}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


async def test_change_password_clears_force_pw_change(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    fake_redis: Any,
) -> None:
    token = await _reset_then_login(api_client, auth_header, fake_redis, api_session)
    resp = await api_client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "NewP@ssw0rd456", "new_password": "Third#Pass789"},
    )
    assert resp.status_code == 200
    login = await api_client.post(
        "/api/auth/login", json={"username": "analyst1", "password": "Third#Pass789"}
    )
    assert login.status_code == 200
    assert login.json()["force_pw_change"] is False


async def test_forced_user_is_blocked_until_change(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    fake_redis: Any,
) -> None:
    token = await _reset_then_login(api_client, auth_header, fake_redis, api_session)
    headers = {"Authorization": f"Bearer {token}"}
    blocked = await api_client.get("/api/auth/users", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Password change required"
    assert (await api_client.get("/api/auth/policy", headers=headers)).status_code == 200
    assert (await api_client.get("/api/auth/me", headers=headers)).status_code == 200


async def test_token_issued_in_revocation_second_is_revoked(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    fake_redis: Any,
) -> None:
    """Menjelaskan mengapa web menunggu 1.200 ms sebelum login ulang: iat <= detik cabut = mati."""
    headers = auth_header(username="analyst1")
    iat = decode_token(headers["Authorization"].split(" ", 1)[1])["iat"]
    await fake_redis.set("revoked_user:analyst1", iat)
    assert (await api_client.get("/api/auth/me", headers=headers)).status_code == 401
    await fake_redis.set("revoked_user:analyst1", iat - 1)
    assert (await api_client.get("/api/auth/me", headers=headers)).status_code == 200


async def test_update_user_client_list(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_user(api_session)
    resp = await api_client.put(
        "/api/auth/users/analyst1/clients",
        headers=auth_header(role="admin"),
        json={"client_ids": ["default"]},
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_update_user_role(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_user(api_session)
    resp = await api_client.put(
        "/api/auth/users/analyst1/role",
        headers=auth_header(role="admin"),
        json={"role": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_audit_log(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_user(api_session)
    await api_client.post("/api/auth/login", json={"username": "analyst1", "password": _PASSWORD})
    resp = await api_client.get("/api/auth/audit-log", headers=auth_header(role="admin"))
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)
