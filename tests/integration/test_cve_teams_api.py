"""API tim pemilik CVE (`/api/cve/teams`): CRUD, soft delete, propagasi rename ke ticket."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_api import deps
from cti_core.db.models.cve import CveOwnerTeam, CveTicket, CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo, AsyncRoleRepo
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

URL = "/api/cve/teams"


@pytest.fixture
async def clients(api_client: AsyncClient, api_session: AsyncSession) -> None:
    repo = AsyncClientRepo(api_session)
    await repo.ensure_default()
    await repo.create(client_id="acme", name="Acme", countries=[])
    await api_session.flush()


@pytest.fixture
def admin(auth_header: Callable[..., dict[str, str]]) -> dict[str, str]:
    return auth_header(username="root", role="superadmin", client_ids=["default", "acme"])


async def _create(
    client: AsyncClient, headers: dict[str, str], name: str = "SOC", **extra: str
) -> dict[str, object]:
    resp = await client.post(URL, headers=headers, json={"name": name, **extra})
    assert resp.status_code == 201, resp.text
    body: dict[str, object] = resp.json()
    return body


async def _tickets(session: AsyncSession, cid: str = "default") -> dict[str, str | None]:
    rows = await session.execute(select(CveTicket).where(CveTicket.client_id == cid))
    return {t.cve_id: t.owner_team for t in rows.scalars()}


async def _seed_tickets(session: AsyncSession, owner: str, cve_ids: list[str]) -> None:
    for i, cve_id in enumerate(cve_ids):
        session.add(CveTracker(cve_id=cve_id, client_id="default", tech="nginx"))
        session.add(
            CveTicket(
                cve_id=cve_id,
                client_id="default",
                ticket_id=f"CTI-2026-11-{owner[:2]}{i}",
                owner_team=owner,
            )
        )
    await session.flush()


@pytest.mark.usefixtures("clients")
async def test_create_and_list_team(
    api_client: AsyncClient, api_session: AsyncSession, admin: dict[str, str]
) -> None:
    await _seed_tickets(api_session, "SOC", ["CVE-2026-8001", "CVE-2026-8002"])
    created = await _create(
        api_client, admin, "  SOC  ", lead_name="Rina", lead_email="rina@example.com"
    )
    assert created["name"] == "SOC"
    assert created["active"] is True

    resp = await api_client.get(URL, headers=admin)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["name"] == "SOC"
    assert item["lead_name"] == "Rina"
    assert item["lead_email"] == "rina@example.com"
    assert item["ticket_count"] == 2


@pytest.mark.usefixtures("clients")
async def test_duplicate_name_case_insensitive_409(
    api_client: AsyncClient, admin: dict[str, str]
) -> None:
    await _create(api_client, admin, "SOC")
    resp = await api_client.post(URL, headers=admin, json={"name": "soc"})
    assert resp.status_code == 409


@pytest.mark.usefixtures("clients")
async def test_rename_conflict_409(api_client: AsyncClient, admin: dict[str, str]) -> None:
    await _create(api_client, admin, "SOC")
    other = await _create(api_client, admin, "NOC")
    resp = await api_client.patch(f"{URL}/{other['id']}", headers=admin, json={"name": "soc"})
    assert resp.status_code == 409


@pytest.mark.usefixtures("clients")
async def test_rename_cascades_to_tickets(
    api_client: AsyncClient, api_session: AsyncSession, admin: dict[str, str]
) -> None:
    await _seed_tickets(api_session, "SOC", ["CVE-2026-8011", "CVE-2026-8012"])
    # Ticket lama dengan spasi di sekitar nama tetap ikut (pembandingan btrim).
    await _seed_tickets(api_session, " SOC ", ["CVE-2026-8013"])
    team = await _create(api_client, admin, "SOC")

    resp = await api_client.patch(f"{URL}/{team['id']}", headers=admin, json={"name": "SecOps"})

    assert resp.status_code == 200
    assert resp.json()["name"] == "SecOps"
    assert resp.json()["ticket_count"] == 3
    api_session.expire_all()
    assert set((await _tickets(api_session)).values()) == {"SecOps"}


@pytest.mark.usefixtures("clients")
async def test_soft_delete_hides_from_default_list(
    api_client: AsyncClient, api_session: AsyncSession, admin: dict[str, str]
) -> None:
    await _seed_tickets(api_session, "SOC", ["CVE-2026-8021"])
    team = await _create(api_client, admin, "SOC")

    resp = await api_client.delete(f"{URL}/{team['id']}", headers=admin)
    assert resp.status_code == 200

    assert (await api_client.get(URL, headers=admin)).json()["items"] == []
    shown = (await api_client.get(f"{URL}?include_inactive=true", headers=admin)).json()["items"]
    assert [(i["name"], i["active"]) for i in shown] == [("SOC", False)]
    api_session.expire_all()
    assert (await _tickets(api_session)) == {"CVE-2026-8021": "SOC"}


@pytest.mark.usefixtures("clients")
async def test_other_client_team_is_404(
    api_client: AsyncClient,
    api_session: AsyncSession,
    admin: dict[str, str],
    auth_header: Callable[..., dict[str, str]],
) -> None:
    team = await _create(api_client, admin, "SOC")
    acme = auth_header(username="amy", role="superadmin", client_ids=["acme"])
    patch = await api_client.patch(f"{URL}/{team['id']}", headers=acme, json={"name": "X"})
    delete = await api_client.delete(f"{URL}/{team['id']}", headers=acme)
    assert patch.status_code == 404
    assert delete.status_code == 404
    api_session.expire_all()
    row = (await api_session.execute(select(CveOwnerTeam))).scalar_one()
    assert (row.name, row.active) == ("SOC", True)


@pytest.mark.usefixtures("clients")
async def test_reader_cannot_create_team(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await AsyncRoleRepo(api_session).upsert_system_role(
        name="cve_reader", display_name="CVE reader", permissions=["view_cve"]
    )
    await api_session.flush()
    deps.invalidate_role_permissions()
    hdr = auth_header(username="reader", role="cve_reader")
    assert (await api_client.get(URL, headers=hdr)).status_code == 200
    assert (await api_client.post(URL, headers=hdr, json={"name": "SOC"})).status_code == 403
    deps.invalidate_role_permissions()


@pytest.mark.usefixtures("clients")
async def test_lead_email_invalid_422(api_client: AsyncClient, admin: dict[str, str]) -> None:
    resp = await api_client.post(URL, headers=admin, json={"name": "SOC", "lead_email": "name@"})
    assert resp.status_code == 422
    ok = await api_client.post(URL, headers=admin, json={"name": "SOC", "lead_email": ""})
    assert ok.status_code == 201


@pytest.mark.usefixtures("clients")
async def test_case_variant_teams_do_not_share_tickets(
    api_client: AsyncClient, api_session: AsyncSession, admin: dict[str, str]
) -> None:
    """Spec 4.5: "SOC" dan "soc" boleh jadi tim terpisah (hasil backfill); ticket tidak dicampur."""
    await _seed_tickets(api_session, "SOC", ["CVE-2026-8031"])
    await _seed_tickets(api_session, "soc", ["CVE-2026-8032"])
    upper = CveOwnerTeam(client_id="default", name="SOC", active=True)
    lower = CveOwnerTeam(client_id="default", name="soc", active=True)
    api_session.add_all([upper, lower])
    await api_session.flush()

    items = (await api_client.get(URL, headers=admin)).json()["items"]
    assert {i["name"]: i["ticket_count"] for i in items} == {"SOC": 1, "soc": 1}

    resp = await api_client.patch(f"{URL}/{upper.id}", headers=admin, json={"name": "Blue team"})
    assert resp.status_code == 200
    assert resp.json()["ticket_count"] == 1
    api_session.expire_all()
    assert await _tickets(api_session) == {
        "CVE-2026-8031": "Blue team",
        "CVE-2026-8032": "soc",
    }
