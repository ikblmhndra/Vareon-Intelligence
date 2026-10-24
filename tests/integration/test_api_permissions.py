"""Permission per route, header client asing, dan PIR lintas client (audit keamanan 2026-10-24)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_api import deps
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _fresh_permission_cache() -> None:
    deps.invalidate_role_permissions()


@pytest.fixture
async def two_clients(api_session: AsyncSession) -> tuple[int, int]:
    repo = AsyncClientRepo(api_session)
    await repo.ensure_default()
    await repo.create(client_id="other", name="Other", countries=[])
    pirs = AsyncPIRRepo(api_session)
    mine = await pirs.create(
        {"title": "Mine", "criteria": {"threat_actors": ["Qilin"]}}, client_id="default"
    )
    theirs = await pirs.create(
        {"title": "Theirs secret", "criteria": {"threat_actors": ["Qilin"]}}, client_id="other"
    )
    await api_session.commit()
    return mine.id, theirs.id


async def test_analyst_cannot_send_newsletter_or_spend_llm(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    analyst = auth_header(username="alice", role="analyst")
    for method, path in (
        ("POST", "/api/newsletter/1/resend"),
        ("POST", "/api/recap/generate"),
        ("POST", "/api/exec/brief"),
        ("POST", "/api/ta/profile/generate"),
        ("POST", "/api/cve/draft-email"),
        ("GET", "/api/auth/users"),
    ):
        r = await api_client.request(method, path, headers=analyst, json={})
        assert r.status_code == 403, (method, path, r.text)
        assert r.json()["detail"].startswith("Missing permission"), (method, path)


async def test_analyst_keeps_reading_and_cve_triage(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]], api_session: AsyncSession
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    await api_session.commit()
    analyst = auth_header(username="alice", role="analyst")
    for path in ("/api/articles", "/api/cve/stats", "/api/data-health", "/api/pir"):
        r = await api_client.get(path, headers=analyst)
        assert r.status_code != 403, (path, r.text)
    # manage_cve: ack CVE yang tidak di-track -> 404 dari handler, bukan 403 dari permission.
    r = await api_client.post("/api/cve/CVE-2099-0001/acknowledge", headers=analyst, json={})
    assert r.status_code == 404, r.text


async def test_foreign_client_header_is_refused(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    two_clients: tuple[int, int],
) -> None:
    analyst = auth_header(username="alice", role="analyst", client_ids=["default"])
    r = await api_client.get("/api/pir", headers={**analyst, "X-Client-ID": "other"})
    assert r.status_code == 403
    ok = await api_client.get("/api/pir", headers={**analyst, "X-Client-ID": "default"})
    assert ok.status_code == 200


async def test_pir_of_another_client_stays_hidden(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    two_clients: tuple[int, int],
) -> None:
    mine, theirs = two_clients
    analyst = auth_header(username="alice", role="analyst", client_ids=["default"])

    assert (await api_client.get(f"/api/crossref/pir/{mine}", headers=analyst)).status_code == 200
    assert (await api_client.get(f"/api/crossref/pir/{theirs}", headers=analyst)).status_code == 404

    ta = (await api_client.get("/api/crossref/ta/Qilin", headers=analyst)).json()
    assert [p["id"] for p in ta["active_pirs"]] == [mine]

    bundle = (await api_client.get("/api/stix/pirs", headers=analyst)).text
    assert "Mine" in bundle and "Theirs secret" not in bundle

    r = await api_client.get(f"/api/mindmap/pir/{theirs}", headers=analyst)
    assert r.status_code == 404
