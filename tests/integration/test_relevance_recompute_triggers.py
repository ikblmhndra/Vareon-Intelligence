"""Perubahan PIR / techstack mengantre `confidence.recompute_all` (P7f): skor prioritas artikel
bergantung pada kecocokan PIR dan aset sendiri, jadi harus dihitung ulang setelah commit.
Exposure/hosting tidak memengaruhi pencocokan, jadi tidak mengantre."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_catalog_api import fid, seed_catalog

pytestmark = pytest.mark.asyncio

_PIR = {"title": "Track APT41", "priority": "P1", "criteria": {"threat_actors": ["Apt41"]}}


@pytest.fixture
def pir_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr("cti_api.routers.pir.send_recompute_all", lambda: calls.append(1))
    return calls


@pytest.fixture
def tech_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr("cti_api.routers.techstack.send_recompute_all", lambda: calls.append(1))
    return calls


async def test_pir_create_update_delete_enqueue_recompute(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    pir_calls: list[int],
) -> None:
    h = auth_header()
    pir_id = (await api_client.post("/api/pir", headers=h, json=_PIR)).json()["id"]
    assert len(pir_calls) == 1
    assert (
        await api_client.put(f"/api/pir/{pir_id}", headers=h, json={"priority": "P2"})
    ).is_success
    assert len(pir_calls) == 2
    assert (await api_client.delete(f"/api/pir/{pir_id}", headers=h)).is_success
    assert len(pir_calls) == 3


async def test_pir_404_does_not_enqueue(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    pir_calls: list[int],
) -> None:
    h = auth_header()
    assert (
        await api_client.put("/api/pir/999999", headers=h, json={"title": "x"})
    ).status_code == 404
    assert (await api_client.delete("/api/pir/999999", headers=h)).status_code == 404
    assert pir_calls == []


async def test_techstack_mutations_enqueue_recompute(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    tech_calls: list[int],
) -> None:
    h = auth_header()
    await seed_catalog(api_session)
    fortios = await fid(api_session, "fortios")
    proxy = await fid(api_session, "fortiproxy")

    entry = (
        await api_client.post("/api/techstack", headers=h, json={"family_id": fortios})
    ).json()["item"]
    assert len(tech_calls) == 1
    base = f"/api/techstack/{entry['id']}"
    assert (await api_client.patch(base, headers=h, json={"active": False})).is_success
    assert len(tech_calls) == 2
    added = await api_client.post(f"{base}/targets", headers=h, json={"family_id": proxy})
    assert added.is_success and len(tech_calls) == 3
    target_id = added.json()["item"]["targets"][0]["id"]
    assert (await api_client.delete(f"{base}/targets/{target_id}", headers=h)).is_success
    assert len(tech_calls) == 4

    # exposure / hosting tidak memengaruhi pencocokan
    assert (
        await api_client.patch(f"{base}/exposure", headers=h, json={"exposure": "public"})
    ).is_success
    assert (
        await api_client.patch(f"{base}/hosting", headers=h, json={"hosting_type": "cloud"})
    ).is_success
    assert len(tech_calls) == 4

    assert (await api_client.delete(base, headers=h)).is_success
    assert len(tech_calls) == 5


async def test_enqueue_failure_keeps_2xx(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> None:
        raise ConnectionError("broker down")

    monkeypatch.setattr("cti_api.routers.pir.send_recompute_all", boom)
    h = auth_header()
    resp = await api_client.post("/api/pir", headers=h, json=_PIR)
    assert resp.status_code == 200
    titles = [p["title"] for p in (await api_client.get("/api/pir", headers=h)).json()]
    assert "Track APT41" in titles
