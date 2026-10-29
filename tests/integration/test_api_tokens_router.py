"""API administrasi token mesin (P7b Task 3): token hanya tampil sekali, pencabutan idempoten."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_api.machine_auth import hash_token
from cti_api.services.roles import ensure_system_roles
from cti_core.db.models.auth import ApiToken, AuditLogEntry
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

URL = "/api/api-tokens"


async def _create(client: AsyncClient, headers: dict[str, str], **body: object):
    return await client.post(URL, headers=headers, json={"name": "splunk", **body})


async def test_create_returns_token_once(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    h = auth_header()
    r = await _create(api_client, h)
    assert r.status_code == 201
    body = r.json()
    assert body["token"].startswith("vrn_")
    assert body["token_prefix"] == body["token"][:12]
    assert body["scopes"] == ["indicators:read"]
    assert body["status"] == "active"
    rows = (await api_client.get(URL, headers=h)).json()
    assert rows and all("token" not in x and "token_hash" not in x for x in rows)


async def test_created_token_hash_matches(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    body = (await _create(api_client, auth_header())).json()
    row = (
        await api_session.execute(select(ApiToken).where(ApiToken.id == body["id"]))
    ).scalar_one()
    assert row.token_hash == hash_token(body["token"])


async def test_create_never_expires(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    body = (await _create(api_client, auth_header(), expires_in_days=None)).json()
    assert body["expires_at"] is None
    assert (await _create(api_client, auth_header())).json()["expires_at"] is not None


@pytest.mark.parametrize(
    "extra",
    [{"max_tlp": "white"}, {"expires_in_days": 0}, {"name": "  "}],
)
async def test_create_validation_422(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]], extra: dict[str, object]
) -> None:
    r = await _create(api_client, auth_header(), **extra)
    assert r.status_code == 422


async def test_revoke_idempotent_and_audited(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    h = auth_header()
    created = (await _create(api_client, h)).json()
    first = await api_client.delete(f"{URL}/{created['id']}", headers=h)
    second = await api_client.delete(f"{URL}/{created['id']}", headers=h)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "revoked"
    assert first.json()["revoked_at"] == second.json()["revoked_at"]
    rows = (
        (
            await api_session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.action.in_(["api_token_create", "api_token_revoke"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert {r.action for r in rows} == {"api_token_create", "api_token_revoke"}
    assert all(created["token"] not in str(r.detail) for r in rows)


async def test_revoke_unknown_404(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    r = await api_client.delete(f"{URL}/999999", headers=auth_header())
    assert r.status_code == 404


async def test_analyst_403(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await ensure_system_roles(api_session)
    h = auth_header(username="alice", role="analyst")
    assert (await api_client.get(URL, headers=h)).status_code == 403
    assert (await _create(api_client, h)).status_code == 403
