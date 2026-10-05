"""Snapshot test `routers/auth.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`).

`POST /login` butuh rate-limit Redis (`is_rate_limited`) -- `api_client`
(`conftest.py`) udah override `get_redis` numpang `_FakeRedis` in-memory
buat SEMUA test, gak butuh Redis server beneran. System roles
(`ensure_system_roles`, biasanya lifespan yang jalanin) di-seed manual
di sini karena lifespan `create_app()` sengaja gak jalan lewat
`ASGITransport` (lihat docstring `api_client`)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_api.security import hash_password
from cti_api.services.roles import ensure_system_roles
from cti_core.db.repositories.auth import AsyncUserRepo
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
    assert resp.json() == snapshot


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
