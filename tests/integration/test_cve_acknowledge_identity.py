"""`acknowledged_by` = username yang login, bukan `analyst_name` dari body.

Dulu `POST /{id}/acknowledge` dan `/bulk-acknowledge` mewajibkan `analyst_name` di body dan
menyimpannya apa adanya (warisan UI lama: kata sandi bersama + nama ketikan). Sekarang tiap user
login sendiri, jadi lewat API siapa pun bisa mengatasnamakan analis lain, dan audit log mencatat dua
nama berbeda untuk satu aksi. FP (`marked_by`) dan `pkg_vuln` (`ack_by`) sudah memakai username
login."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.cve import CveTracker
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

CVES = ["CVE-2026-0801", "CVE-2026-0802"]
ALICE = "alice"
SPOOFED = {"analyst_name": "bob"}


@pytest.fixture
def alice(auth_header: Callable[..., dict[str, str]]) -> dict[str, str]:
    return auth_header(username=ALICE, role="analyst")


@pytest.fixture
async def tracked(api_client: AsyncClient, api_session: AsyncSession) -> None:
    api_session.add_all(CveTracker(cve_id=c, client_id="default", tech="nginx") for c in CVES)
    await api_session.flush()


async def acknowledged_by(client: AsyncClient, headers: dict[str, str], cve_id: str) -> str:
    return (await client.get(f"/api/cve/{cve_id}/ticket", headers=headers)).json()[
        "acknowledged_by"
    ]


@pytest.mark.usefixtures("tracked")
async def test_acknowledge_records_the_logged_in_user_not_the_name_in_the_body(
    api_client: AsyncClient, alice: dict[str, str]
) -> None:
    resp = await api_client.post(f"/api/cve/{CVES[0]}/acknowledge", headers=alice, json=SPOOFED)

    assert resp.status_code == 200
    assert await acknowledged_by(api_client, alice, CVES[0]) == ALICE


@pytest.mark.usefixtures("tracked")
async def test_acknowledge_needs_no_body(api_client: AsyncClient, alice: dict[str, str]) -> None:
    resp = await api_client.post(f"/api/cve/{CVES[0]}/acknowledge", headers=alice)

    assert resp.status_code == 200
    assert await acknowledged_by(api_client, alice, CVES[0]) == ALICE


@pytest.mark.usefixtures("tracked")
async def test_bulk_acknowledge_records_the_logged_in_user_not_the_name_in_the_body(
    api_client: AsyncClient, alice: dict[str, str]
) -> None:
    resp = await api_client.post(
        "/api/cve/bulk-acknowledge", headers=alice, json={"cve_ids": CVES, **SPOOFED}
    )

    assert resp.json() == {"ok": True, "acknowledged": len(CVES)}
    assert [await acknowledged_by(api_client, alice, c) for c in CVES] == [ALICE, ALICE]


@pytest.mark.usefixtures("tracked")
async def test_bulk_acknowledge_needs_only_cve_ids(
    api_client: AsyncClient, alice: dict[str, str]
) -> None:
    resp = await api_client.post("/api/cve/bulk-acknowledge", headers=alice, json={"cve_ids": CVES})

    assert resp.status_code == 200


@pytest.mark.usefixtures("tracked")
async def test_audit_log_of_acknowledge_carries_no_second_name(
    api_client: AsyncClient, api_session: AsyncSession, alice: dict[str, str]
) -> None:
    await api_client.post(f"/api/cve/{CVES[0]}/acknowledge", headers=alice, json=SPOOFED)
    await api_client.post(
        "/api/cve/bulk-acknowledge", headers=alice, json={"cve_ids": [CVES[1]], **SPOOFED}
    )

    entries = (
        (
            await api_session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.action.in_(["acknowledge_cve", "bulk_acknowledge_cve"])
                )
            )
        )
        .scalars()
        .all()
    )

    assert sorted((e.action, e.username) for e in entries) == [
        ("acknowledge_cve", ALICE),
        ("bulk_acknowledge_cve", ALICE),
    ]
    assert not any("bob" in str(e.detail) for e in entries)
