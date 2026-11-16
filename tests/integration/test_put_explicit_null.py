"""PUT RFI/PIR: null eksplisit mengosongkan kolom nullable (due_date, linked_pir, start/end_date).

Kolom NOT NULL (question, title) yang dikirim null tetap tak berubah; kolom yang tak dikirim juga.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from cti_core.db.repositories.rfi import AsyncRFIRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_DUE = datetime.date(2026, 12, 1)


async def _seed_rfi(session: AsyncSession) -> int:
    await AsyncClientRepo(session).ensure_default()
    pir = await AsyncPIRRepo(session).create({"title": "P"}, client_id="default")
    rfi = await AsyncRFIRepo(session).create(
        {"requester": "CISO", "question": "Q?", "due_date": _DUE, "linked_pir": pir.id},
        client_id="default",
    )
    await session.commit()
    return rfi.id


async def test_put_rfi_null_clears_nullable(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    rid = await _seed_rfi(api_session)
    resp = await api_client.put(
        f"/api/rfi/{rid}", headers=auth_header(), json={"due_date": None, "linked_pir": None}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["due_date"] is None
    assert body["linked_pir"] is None
    assert body["question"] == "Q?"


async def test_put_rfi_null_not_null_column_unchanged(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    rid = await _seed_rfi(api_session)
    resp = await api_client.put(
        f"/api/rfi/{rid}",
        headers=auth_header(),
        json={"question": None, "requester": None, "status": None, "response": None},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["question"], body["requester"], body["status"]) == ("Q?", "CISO", "open")
    assert body["response"] == ""
    assert body["due_date"] == _DUE.isoformat()
    assert body["linked_pir"] is not None


async def test_put_rfi_omitted_unchanged(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    rid = await _seed_rfi(api_session)
    resp = await api_client.put(f"/api/rfi/{rid}", headers=auth_header(), json={"response": "A"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["response"] == "A"
    assert body["due_date"] == _DUE.isoformat()
    assert body["linked_pir"] is not None


async def test_put_pir_null_clears_dates_and_keeps_title(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    pir = await AsyncPIRRepo(api_session).create(
        {"title": "Keep", "start_date": _DUE, "end_date": _DUE}, client_id="default"
    )
    await api_session.commit()
    resp = await api_client.put(
        f"/api/pir/{pir.id}",
        headers=auth_header(),
        json={"end_date": None, "title": None},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["end_date"] is None
    assert body["title"] == "Keep"
    assert body["start_date"] == _DUE.isoformat()  # tak dikirim = tak berubah

    resp = await api_client.put(
        f"/api/pir/{pir.id}", headers=auth_header(), json={"start_date": None}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["start_date"] is None
