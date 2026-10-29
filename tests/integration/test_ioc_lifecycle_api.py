"""API siklus hidup indikator (P7a Task 5): revoke/restore lewat feedback, marking, filter state."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_api.services.roles import ensure_system_roles
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.indicator import Indicator
from cti_core.db.repositories.auth import AsyncRoleRepo
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_KEYS = ("state", "valid_from", "valid_until", "revoked_at", "revoked_by", "tlp", "pap")


async def _ioc(session: AsyncSession, value: str = "45.33.32.156", type: str = "ip"):
    ind = await AsyncIndicatorRepo(session).upsert(
        type=type, value=value, source_url="https://a.example/r", source_name="A"
    )
    await session.commit()
    return ind


async def _ioc_reader(session: AsyncSession) -> str:
    """Role uji yang hanya boleh melihat IOC (sejak 0.8.11 role sistem `analyst` punya
    `manage_ioc`, jadi tidak bisa lagi dipakai sebagai contoh user tanpa izin itu)."""
    await AsyncRoleRepo(session).create(
        name="ioc-reader", display_name="IOC reader", permissions=["view_ioc"], created_by="test"
    )
    await session.commit()
    return "ioc-reader"


async def _fb(client, headers, ioc_id, verdict):
    return await client.post(
        f"/api/iocs/{ioc_id}/feedback", headers=headers, json={"verdict": verdict}
    )


async def test_fp_revokes(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    ind = await _ioc(api_session)
    h = auth_header(username="bob")
    r1 = await _fb(api_client, h, ind.id, "fp")
    assert r1.status_code == 200, r1.text
    assert r1.json()["state"] == "revoked"
    assert r1.json()["revoked_by"] == "bob"
    first = r1.json()["revoked_at"]
    r2 = await _fb(api_client, auth_header(username="carol"), ind.id, "fp")
    assert r2.json()["revoked_at"] == first
    assert r2.json()["revoked_by"] == "bob"


async def test_tp_restores(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    ind = await _ioc(api_session)
    h = auth_header()
    await _fb(api_client, h, ind.id, "fp")
    r = await _fb(api_client, h, ind.id, "tp")
    body = r.json()
    assert body["state"] == "active"
    assert body["revoked_at"] is None
    assert body["tp_count"] == 1


async def test_feedback_requires_manage_ioc(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    ind = await _ioc(api_session)
    role = await _ioc_reader(api_session)
    r = await _fb(api_client, auth_header(username="alice", role=role), ind.id, "fp")
    assert r.status_code == 403


async def test_analyst_can_revoke(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await ensure_system_roles(api_session)
    ind = await _ioc(api_session)
    r = await _fb(api_client, auth_header(username="alice", role="analyst"), ind.id, "fp")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "revoked"


async def test_patch_marking(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    ind = await _ioc(api_session)
    url = f"/api/iocs/{ind.id}/marking"
    r = await api_client.patch(url, headers=auth_header(), json={"tlp": "amber"})
    assert r.status_code == 200, r.text
    assert r.json()["tlp"] == "amber"
    assert r.json()["pap"] == "clear"
    rows = (
        (
            await api_session.execute(
                select(AuditLogEntry).where(AuditLogEntry.action == "ioc_marking")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    bad = await api_client.patch(url, headers=auth_header(), json={"tlp": "purple"})
    assert bad.status_code == 422
    role = await _ioc_reader(api_session)
    denied = await api_client.patch(
        url, headers=auth_header(username="alice", role=role), json={"tlp": "red"}
    )
    assert denied.status_code == 403
    missing = await api_client.patch(
        "/api/iocs/999999/marking", headers=auth_header(), json={"tlp": "red"}
    )
    assert missing.status_code == 404


async def test_list_state_filter(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    a = await _ioc(api_session, "1.1.1.1")
    e = await _ioc(api_session, "2.2.2.2")
    v = await _ioc(api_session, "3.3.3.3")
    await api_session.execute(
        update(Indicator)
        .where(Indicator.id == e.id)
        .values(valid_until=now - datetime.timedelta(days=1))
    )
    await api_session.execute(
        update(Indicator).where(Indicator.id == v.id).values(revoked_at=now, revoked_by="x")
    )
    await api_session.commit()
    h = auth_header()
    r = await api_client.get("/api/iocs", headers=h, params={"state": "expired"})
    assert [i["value"] for i in r.json()["iocs"]] == ["2.2.2.2"]
    r = await api_client.get("/api/iocs", headers=h)
    values = {i["value"] for i in r.json()["iocs"]}
    assert values == {"1.1.1.1", "2.2.2.2", "3.3.3.3"}
    assert a.id


async def test_list_state_allowlisted_ignores_include_suppressed(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    ind = await AsyncIndicatorRepo(api_session).upsert(
        type="ip",
        value="9.9.9.9",
        source_url="https://a.example/r",
        source_name="A",
        suppression_reason="allowlist: test",
    )
    await api_session.commit()
    assert ind.auto_suppressed
    r = await api_client.get("/api/iocs", headers=auth_header(), params={"state": "allowlisted"})
    assert [i["value"] for i in r.json()["iocs"]] == ["9.9.9.9"]


async def test_detail_has_lifecycle_fields(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _ioc(api_session)
    r = await api_client.get("/api/iocs/ip/45.33.32.156", headers=auth_header())
    assert r.status_code == 200
    for k in _KEYS:
        assert k in r.json(), k
