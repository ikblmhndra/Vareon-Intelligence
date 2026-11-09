"""`PUT /api/cve/{id}/ticket` dan eskalasi: hanya transisi mati -> nyala yang mengantre draf email
ke lead tim; simpan ulang tidak menggandakan; broker mati tidak menggagalkan simpan."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from cti_api.services import cve_escalation
from cti_core.db.models.cve import CveOwnerTeam, CveTicket, CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

CVE = "CVE-2026-7001"


class FakeCelery:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict[str, Any]] = []

    def send_task(
        self,
        name: str,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        **opts: Any,
    ) -> SimpleNamespace:
        if self.fail:
            raise ConnectionError("broker mati")
        self.sent.append({"name": name, "kwargs": kwargs or {}, **opts})
        return SimpleNamespace(id="t")


@pytest.fixture
def celery(monkeypatch: pytest.MonkeyPatch) -> FakeCelery:
    fake = FakeCelery()
    monkeypatch.setattr(cve_escalation, "get_celery_client", lambda: fake)
    return fake


@pytest.fixture
async def seeded(api_client: AsyncClient, api_session: AsyncSession) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    api_session.add(CveTracker(cve_id=CVE, client_id="default", tech="nginx"))
    api_session.add(
        CveOwnerTeam(client_id="default", name="SOC", lead_email="lead@example.com", active=True)
    )
    api_session.add(CveOwnerTeam(client_id="default", name="NoLead", active=True))
    await api_session.flush()


@pytest.fixture
def headers(auth_header: Callable[..., dict[str, str]]) -> dict[str, str]:
    return auth_header(username="tester", role="superadmin", client_ids=["default"])


async def _put(
    client: AsyncClient, headers: dict[str, str], *, team: str = "SOC", escalate: bool = True
) -> Any:
    return await client.put(
        f"/api/cve/{CVE}/ticket",
        headers=headers,
        json={"owner_team": team, "escalation_required": escalate},
    )


async def _ticket(session: AsyncSession) -> CveTicket:
    session.expire_all()
    return (await session.execute(select(CveTicket).where(CveTicket.cve_id == CVE))).scalar_one()


@pytest.mark.usefixtures("seeded")
async def test_turning_escalation_on_queues_once(
    api_client: AsyncClient, headers: dict[str, str], celery: FakeCelery
) -> None:
    resp = await _put(api_client, headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "escalation": "queued"}
    assert len(celery.sent) == 1
    assert celery.sent[0]["name"] == "cve.notify_escalation"
    assert celery.sent[0]["kwargs"] == {"client_id": "default", "cve_id": CVE, "actor": "tester"}
    assert celery.sent[0]["queue"] == "notify"


@pytest.mark.usefixtures("seeded")
async def test_resave_escalated_ticket_sends_nothing(
    api_client: AsyncClient, headers: dict[str, str], celery: FakeCelery
) -> None:
    await _put(api_client, headers)
    resp = await _put(api_client, headers)
    assert resp.json()["escalation"] == "not_needed"
    assert len(celery.sent) == 1


@pytest.mark.usefixtures("seeded")
async def test_turning_off_resets_notified_at(
    api_client: AsyncClient, api_session: AsyncSession, headers: dict[str, str], celery: FakeCelery
) -> None:
    await _put(api_client, headers)
    (await _ticket(api_session)).escalation_notified_at = datetime.datetime.now(datetime.UTC)
    await api_session.flush()
    resp = await _put(api_client, headers, escalate=False)
    assert resp.json()["escalation"] == "not_needed"
    assert (await _ticket(api_session)).escalation_notified_at is None
    await _put(api_client, headers)  # nyala lagi = draf baru
    assert len(celery.sent) == 2


@pytest.mark.usefixtures("seeded")
async def test_unknown_team_gives_no_lead(
    api_client: AsyncClient, headers: dict[str, str], celery: FakeCelery
) -> None:
    resp = await _put(api_client, headers, team="Nobody")
    assert resp.json()["escalation"] == "no_lead"
    assert celery.sent == []


@pytest.mark.usefixtures("seeded")
async def test_team_without_lead_email_gives_no_lead(
    api_client: AsyncClient, headers: dict[str, str], celery: FakeCelery
) -> None:
    resp = await _put(api_client, headers, team="NoLead")
    assert resp.json()["escalation"] == "no_lead"
    assert celery.sent == []


@pytest.mark.usefixtures("seeded")
async def test_broker_down_still_saves(
    api_client: AsyncClient,
    api_session: AsyncSession,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cve_escalation, "get_celery_client", lambda: FakeCelery(fail=True))
    resp = await _put(api_client, headers)
    assert resp.status_code == 200
    assert resp.json()["escalation"] == "failed"
    assert (await _ticket(api_session)).escalation_required is True
