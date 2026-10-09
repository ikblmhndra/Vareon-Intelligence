"""FP, ticket, dan ack hanya untuk CVE yang ada di tracker client pemanggil (selain update ticket
yang sudah ada).

FP, ticket, dan ack berkunci `(cve_id, client_id)` tanpa FK ke tracker. Dulu id apa pun yang
formatnya valid bisa dibuatkan baris: ticket yatim sejak lahir, atau penanda FP untuk CVE yang tidak
pernah di-track client itu. Sekarang `404` dan tidak ada yang ditulis. Pengecualian: CVE yang SUDAH
punya ticket (mis. yatim sesudah purge) tetap boleh diubah, supaya ticket yang ada tidak terkunci.
`DELETE /false-positive` dan `GET /ticket` tidak diperiksa (membersihkan penanda lama; GET `{}`)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo, AsyncCveTicketRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

TRACKED = "CVE-2026-1001"
UNTRACKED = "CVE-2026-1002"


@pytest.fixture
async def tracked(api_client: AsyncClient, api_session: AsyncSession) -> None:
    api_session.add(CveTracker(cve_id=TRACKED, client_id="default", tech="nginx"))
    await api_session.flush()


@pytest.fixture
def analyst(auth_header: Callable[..., dict[str, str]]) -> dict[str, str]:
    return auth_header(username="alice", role="analyst")


async def ticket_of(client: AsyncClient, headers: dict[str, str], cve_id: str) -> dict[str, object]:
    return (await client.get(f"/api/cve/{cve_id}/ticket", headers=headers)).json()


@pytest.mark.usefixtures("tracked")
async def test_false_positive_for_an_untracked_cve_is_404_and_writes_nothing(
    api_client: AsyncClient, api_session: AsyncSession, analyst: dict[str, str]
) -> None:
    resp = await api_client.post(f"/api/cve/{UNTRACKED}/false-positive", headers=analyst)

    assert resp.status_code == 404
    assert await AsyncCveFalsePositiveRepo(api_session).list_cve_ids("default") == []


@pytest.mark.usefixtures("tracked")
async def test_bulk_false_positive_with_an_untracked_id_is_404_and_marks_nothing(
    api_client: AsyncClient, api_session: AsyncSession, analyst: dict[str, str]
) -> None:
    resp = await api_client.post(
        "/api/cve/bulk-false-positive", headers=analyst, json={"cve_ids": [TRACKED, UNTRACKED]}
    )

    assert resp.status_code == 404
    assert UNTRACKED in resp.json()["detail"]
    assert await AsyncCveFalsePositiveRepo(api_session).list_cve_ids("default") == []


@pytest.mark.usefixtures("tracked")
async def test_a_stale_false_positive_mark_can_still_be_removed(
    api_client: AsyncClient, api_session: AsyncSession, analyst: dict[str, str]
) -> None:
    fp = AsyncCveFalsePositiveRepo(api_session)
    await fp.mark(UNTRACKED, "default")

    resp = await api_client.delete(f"/api/cve/{UNTRACKED}/false-positive", headers=analyst)

    assert resp.status_code == 200
    assert await fp.list_cve_ids("default") == []


@pytest.mark.usefixtures("tracked")
async def test_acknowledge_for_an_untracked_cve_is_404_and_creates_no_ticket(
    api_client: AsyncClient, analyst: dict[str, str]
) -> None:
    resp = await api_client.post(f"/api/cve/{UNTRACKED}/acknowledge", headers=analyst)

    assert resp.status_code == 404
    assert await ticket_of(api_client, analyst, UNTRACKED) == {}


@pytest.mark.usefixtures("tracked")
async def test_bulk_acknowledge_with_an_untracked_id_is_404_and_acknowledges_nothing(
    api_client: AsyncClient, analyst: dict[str, str]
) -> None:
    resp = await api_client.post(
        "/api/cve/bulk-acknowledge", headers=analyst, json={"cve_ids": [TRACKED, UNTRACKED]}
    )

    assert resp.status_code == 404
    assert UNTRACKED in resp.json()["detail"]
    assert await ticket_of(api_client, analyst, TRACKED) == {}


@pytest.mark.usefixtures("tracked")
async def test_saving_a_ticket_for_an_untracked_cve_is_404_and_creates_nothing(
    api_client: AsyncClient, analyst: dict[str, str]
) -> None:
    resp = await api_client.put(
        f"/api/cve/{UNTRACKED}/ticket", headers=analyst, json={"comments": "x"}
    )

    assert resp.status_code == 404
    assert await ticket_of(api_client, analyst, UNTRACKED) == {}


@pytest.mark.usefixtures("tracked")
async def test_an_orphaned_ticket_can_still_be_updated_and_acknowledged(
    api_client: AsyncClient, api_session: AsyncSession, analyst: dict[str, str]
) -> None:
    await AsyncCveTicketRepo(api_session).upsert(
        cve_id=UNTRACKED, client_id="default", comments="old"
    )

    saved = await api_client.put(
        f"/api/cve/{UNTRACKED}/ticket", headers=analyst, json={"comments": "new"}
    )
    acked = await api_client.post(f"/api/cve/{UNTRACKED}/acknowledge", headers=analyst)

    assert (saved.status_code, acked.status_code) == (200, 200)
    ticket = await ticket_of(api_client, analyst, UNTRACKED)
    assert (ticket["comments"], ticket["acknowledged_by"]) == ("new", "alice")


@pytest.mark.usefixtures("tracked")
async def test_bulk_acknowledge_accepts_an_orphaned_ticket(
    api_client: AsyncClient, api_session: AsyncSession, analyst: dict[str, str]
) -> None:
    await AsyncCveTicketRepo(api_session).upsert(
        cve_id=UNTRACKED, client_id="default", comments="old"
    )

    resp = await api_client.post(
        "/api/cve/bulk-acknowledge", headers=analyst, json={"cve_ids": [TRACKED, UNTRACKED]}
    )

    assert resp.json() == {"ok": True, "acknowledged": 2}


@pytest.mark.usefixtures("tracked")
async def test_another_clients_tracker_and_ticket_do_not_count(
    api_client: AsyncClient,
    api_session: AsyncSession,
    analyst: dict[str, str],
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await AsyncClientRepo(api_session).create(client_id="acme", name="Acme", countries=[])
    await api_client.post(
        f"/api/cve/{TRACKED}/acknowledge", headers=analyst
    )  # tiket client default
    acme = {**auth_header(role="analyst", client_ids=["default", "acme"]), "X-Client-ID": "acme"}

    responses = [
        await api_client.post(f"/api/cve/{TRACKED}/false-positive", headers=acme),
        await api_client.post(f"/api/cve/{TRACKED}/acknowledge", headers=acme),
        await api_client.put(f"/api/cve/{TRACKED}/ticket", headers=acme, json={"comments": "x"}),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
