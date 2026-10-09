"""`POST /{cve_id}/acknowledge`: ack pertama menang.

Ack ulang (misalnya oleh analis lain) tetap `200`, tetapi tidak mengubah apa pun: nama, waktu ack
(dasar MTTA di dashboard), dan nomor ticket. Sama dengan `bulk-acknowledge`, yang melewati CVE yang
sudah di-ack. Dulu ack ulang menimpa semuanya."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from cti_core.db.models.cve import CveTracker
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

CVE = "CVE-2026-0901"


@pytest.fixture
async def tracked(api_client: AsyncClient, api_session: AsyncSession) -> None:
    api_session.add(CveTracker(cve_id=CVE, client_id="default", tech="nginx"))
    await api_session.flush()


async def acknowledge(client: AsyncClient, headers: dict[str, str], name: str) -> httpx.Response:
    # `analyst_name` tetap dikirim supaya tes ini tak bergantung pada apakah body-nya sudah dihapus
    # (nama itu juga username yang login, jadi hasilnya sama di kedua kontrak).
    return await client.post(
        f"/api/cve/{CVE}/acknowledge", headers=headers, json={"analyst_name": name}
    )


@pytest.mark.usefixtures("tracked")
async def test_a_second_analyst_acknowledging_changes_nothing(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    alice, bob = auth_header(username="alice"), auth_header(username="bob")
    await acknowledge(api_client, alice, "alice")
    ticket = (await api_client.get(f"/api/cve/{CVE}/ticket", headers=alice)).json()

    resp = await acknowledge(api_client, bob, "bob")

    assert (resp.status_code, resp.json()) == (200, {"ok": True})
    assert (await api_client.get(f"/api/cve/{CVE}/ticket", headers=bob)).json() == ticket
    assert ticket["acknowledged_by"] == "alice"
