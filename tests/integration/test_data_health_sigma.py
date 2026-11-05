"""Blok `sigma` di `GET /api/data-health` (P7e): status dari jumlah aturan, umur snapshot, error."""

from __future__ import annotations

import datetime
import uuid

import pytest
from cti_core.db.models import SigmaRule
from cti_core.db.models.entity import ReferenceSnapshot
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


async def _reset(s: AsyncSession) -> None:
    # bootstrap lifespan bisa meninggalkan snapshot bawaan di DB bersama
    await s.execute(delete(SigmaRule))
    await s.execute(delete(ReferenceSnapshot).where(ReferenceSnapshot.name == "sigma"))


async def _seed(
    s: AsyncSession, *, rules: int, age_days: int = 1, last_error: str | None = None
) -> None:
    await _reset(s)
    for i in range(rules):
        s.add(
            SigmaRule(
                id=uuid.UUID(int=i + 1),
                title=f"R{i}",
                level="high",
                status="test",
                ruleset="core",
                logsource={},
                techniques=[],
                path=f"rules/r{i}.yml",
                release="r1",
                yaml="title: x",
            )
        )
    s.add(
        ReferenceSnapshot(
            name="sigma",
            fetched_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=age_days),
            sha256="0" * 64,
            content={
                "release": "r1",
                "rules": rules,
                "skipped": 0,
                "source_url": "u",
                "last_error": last_error,
            },
        )
    )
    await s.flush()


@pytest.mark.parametrize(
    ("rules", "age_days", "last_error", "status"),
    [
        (2, 1, None, "ok"),
        (2, 61, None, "amber"),
        (2, 1, "boom", "amber"),
        (0, 1, None, "red"),
    ],
)
async def test_data_health_sigma_status(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header,
    rules,
    age_days,
    last_error,
    status,
) -> None:
    await _seed(api_session, rules=rules, age_days=age_days, last_error=last_error)
    body = (await api_client.get("/api/data-health", headers=auth_header(role="analyst"))).json()
    sg = body["sigma"]
    assert sg["status"] == status
    assert sg["rules"] == rules
    assert sg["release"] == "r1"
    assert sg["last_error"] == last_error
    assert sg["fetched_at"] is not None


async def test_data_health_sigma_no_snapshot(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    await _reset(api_session)
    await api_session.flush()
    body = (await api_client.get("/api/data-health", headers=auth_header(role="analyst"))).json()
    assert body["sigma"]["status"] == "red"
    assert body["sigma"]["release"] is None
    assert body["sigma"]["fetched_at"] is None


@pytest.mark.parametrize(
    ("content", "release", "last_error", "status"),
    [
        ([], None, None, "ok"),
        ({"release": 7, "last_error": 123}, "7", "123", "amber"),
        ({"last_error": {"a": 1}}, None, "{'a': 1}", "amber"),
    ],
)
async def test_data_health_sigma_malformed_snapshot(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header,
    content,
    release,
    last_error,
    status,
) -> None:
    await _seed(api_session, rules=2)
    snap = await api_session.get(ReferenceSnapshot, "sigma")
    snap.content = content
    await api_session.flush()
    resp = await api_client.get("/api/data-health", headers=auth_header(role="analyst"))
    assert resp.status_code == 200
    sg = resp.json()["sigma"]
    assert (sg["release"], sg["last_error"], sg["status"]) == (release, last_error, status)
