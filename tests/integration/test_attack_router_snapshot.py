"""Snapshot test `routers/attack.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`).

`POST /sync`/`GET /sync/{domain_key}` jalanin `BackgroundTasks` yang
beneran ke-`await` SEBELUM `httpx.ASGITransport` balikin response (jadi
efektif SINKRON di test ini) -- `AsyncAttackSyncRepo.sync_domain()` asli
manggil `httpx.AsyncClient` ke GitHub (STIX bundle MITRE) SUNGGUHAN,
di-mock di sini (class-level patch, `AsyncMock`) biar test gak butuh
jaringan sama sekali."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import pytest
from cti_core.db.models.attack import (
    AttackGroup,
    AttackMitigation,
    AttackSoftware,
    AttackTactic,
    AttackTechnique,
)
from cti_core.db.repositories.attack import AsyncAttackSyncRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_NORMALIZE = path_type(
    {
        r"(.*\.)?created_at$": (str,),
        r"(.*\.)?updated_at$": (str,),
    },
    regex=True,
    strict=False,
)


async def _seed(session: AsyncSession) -> None:
    session.add_all(
        [
            AttackTechnique(
                stix_id="attack-pattern--0001",
                attack_id="T1566",
                name="Phishing",
                description="Adversaries send phishing messages.",
                tactics=["initial-access"],
                domains=["enterprise-attack"],
            ),
            AttackTactic(
                stix_id="x-mitre-tactic--0001",
                tactic_id="TA0001",
                name="Initial Access",
                shortname="initial-access",
                domains=["enterprise-attack"],
            ),
            AttackMitigation(
                stix_id="course-of-action--0001",
                mitigation_id="M1049",
                name="Antivirus/Antimalware",
                domains=["enterprise-attack"],
            ),
            AttackGroup(
                stix_id="intrusion-set--0001",
                group_id="G0096",
                name="APT41",
                domains=["enterprise-attack"],
            ),
            AttackSoftware(
                stix_id="malware--0001",
                software_id="S0002",
                name="Mimikatz",
                software_type="tool",
                domains=["enterprise-attack"],
            ),
        ]
    )
    await session.flush()


async def test_attack_status(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/attack/status", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_attack_sync(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    with patch.object(AsyncAttackSyncRepo, "sync_domain", AsyncMock(return_value={})):
        resp = await api_client.post(
            "/api/attack/sync", headers=auth_header(role="admin"), json={"domains": ["enterprise"]}
        )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_attack_sync_single(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    with patch.object(AsyncAttackSyncRepo, "sync_domain", AsyncMock(return_value={})):
        resp = await api_client.get(
            "/api/attack/sync/enterprise", headers=auth_header(role="admin")
        )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_attack_navigator_layer(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed(api_session)
    resp = await api_client.get("/api/attack/navigator-layer", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)
