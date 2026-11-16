"""Alasan + catatan false-positive: disimpan di `cve_false_positives`, tampil di `CveOut`, dan
tab "False positive" (`fp_only`) hanya memuat CVE yang ditandai client pemanggil."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

ID_A = "CVE-2026-2001"
ID_B = "CVE-2026-2002"


@pytest.fixture
async def tracked(api_client: AsyncClient, api_session: AsyncSession) -> None:
    clients = AsyncClientRepo(api_session)
    await clients.ensure_default()
    await clients.create(client_id="acme", name="Acme", countries=[])
    api_session.add_all(
        [
            CveTracker(cve_id=ID_A, client_id="default", tech="nginx"),
            CveTracker(cve_id=ID_B, client_id="default", tech="nginx"),
            CveTracker(cve_id=ID_A, client_id="acme", tech="nginx"),
        ]
    )
    await api_session.flush()


@pytest.fixture
def analyst(auth_header: Callable[..., dict[str, str]]) -> dict[str, str]:
    return auth_header(username="alice", role="analyst")


async def fp_list(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, object]]:
    resp = await client.get("/api/cve?fp_only=true", headers=headers)
    assert resp.status_code == 200
    return resp.json()["cves"]


@pytest.mark.usefixtures("tracked")
async def test_unknown_reason_is_422(api_client: AsyncClient, analyst: dict[str, str]) -> None:
    resp = await api_client.post(
        f"/api/cve/{ID_A}/false-positive", headers=analyst, json={"reason": "bogus"}
    )
    assert resp.status_code == 422


@pytest.mark.usefixtures("tracked")
async def test_other_without_note_is_422(api_client: AsyncClient, analyst: dict[str, str]) -> None:
    resp = await api_client.post(
        f"/api/cve/{ID_A}/false-positive", headers=analyst, json={"reason": "other", "note": " "}
    )
    assert resp.status_code == 422


@pytest.mark.usefixtures("tracked")
async def test_mark_with_reason_serialises_fp_fields(
    api_client: AsyncClient, analyst: dict[str, str]
) -> None:
    resp = await api_client.post(
        f"/api/cve/{ID_A}/false-positive",
        headers=analyst,
        json={"reason": "duplicate", "note": "sama dengan CVE lain"},
    )
    assert resp.status_code == 200

    rows = await fp_list(api_client, analyst)

    assert [r["cve_id"] for r in rows] == [ID_A]
    row = rows[0]
    assert row["false_positive"] is True
    assert row["fp_reason"] == "duplicate"
    assert row["fp_note"] == "sama dengan CVE lain"
    assert row["fp_marked_by"] == "alice"
    assert row["fp_marked_at"] != ""
    stats = (await api_client.get("/api/cve/stats?fp_only=true", headers=analyst)).json()
    assert stats["total"] == 1


@pytest.mark.usefixtures("tracked")
async def test_remark_updates_reason(api_client: AsyncClient, analyst: dict[str, str]) -> None:
    url = f"/api/cve/{ID_A}/false-positive"
    await api_client.post(url, headers=analyst, json={"reason": "duplicate"})
    await api_client.post(url, headers=analyst, json={"reason": "not_in_stack"})

    rows = await fp_list(api_client, analyst)

    assert len(rows) == 1
    assert rows[0]["fp_reason"] == "not_in_stack"


@pytest.mark.usefixtures("tracked")
async def test_audit_detail_has_reason(
    api_client: AsyncClient, api_session: AsyncSession, analyst: dict[str, str]
) -> None:
    await api_client.post(
        f"/api/cve/{ID_A}/false-positive", headers=analyst, json={"reason": "duplicate"}
    )

    row = (
        await api_session.execute(
            select(AuditLogEntry).where(AuditLogEntry.action == "mark_false_positive")
        )
    ).scalar_one()
    assert row.detail == {"reason": "duplicate"}


@pytest.mark.usefixtures("tracked")
async def test_bodiless_post_still_200(api_client: AsyncClient, analyst: dict[str, str]) -> None:
    resp = await api_client.post(f"/api/cve/{ID_A}/false-positive", headers=analyst)
    assert resp.status_code == 200

    rows = await fp_list(api_client, analyst)

    assert rows[0]["fp_reason"] == ""
    assert rows[0]["fp_note"] == ""


@pytest.mark.usefixtures("tracked")
async def test_bulk_reason_applies_to_all(api_client: AsyncClient, analyst: dict[str, str]) -> None:
    resp = await api_client.post(
        "/api/cve/bulk-false-positive",
        headers=analyst,
        json={"cve_ids": [ID_A, ID_B], "reason": "not_in_stack"},
    )
    assert resp.status_code == 200

    rows = await fp_list(api_client, analyst)

    assert {r["cve_id"]: r["fp_reason"] for r in rows} == {
        ID_A: "not_in_stack",
        ID_B: "not_in_stack",
    }


@pytest.mark.usefixtures("tracked")
async def test_other_client_cannot_see_fp_reason(
    api_client: AsyncClient,
    analyst: dict[str, str],
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await api_client.post(
        f"/api/cve/{ID_A}/false-positive", headers=analyst, json={"reason": "duplicate"}
    )

    acme = auth_header(username="bob", role="analyst", client_ids=["acme"])
    resp = await api_client.get("/api/cve", headers=acme)

    row = next(r for r in resp.json()["cves"] if r["cve_id"] == ID_A)
    assert row["false_positive"] is False
    assert row["fp_reason"] == ""
    assert await fp_list(api_client, acme) == []
