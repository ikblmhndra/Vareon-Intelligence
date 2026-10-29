"""Interop dengan klien TAXII 2.1 sungguhan (`taxii2-client`, dev-only): app disajikan oleh
uvicorn di event loop test yang sama (jadi `api_session` aman dipakai bersama), klien sinkron
berjalan di thread lewat `asyncio.to_thread`."""

from __future__ import annotations

import asyncio
import datetime
import socket
from collections.abc import AsyncIterator

import pytest
import uvicorn
from cti_api import machine_auth
from cti_api.services import feed
from cti_core.db.models.indicator import Indicator
from cti_core.db.repositories.auth import AsyncApiTokenRepo
from cti_core.indicator.stix_id import indicator_uuid
from sqlalchemy.ext.asyncio import AsyncSession
from taxii2client.v21 import Server, as_pages

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def base_url(api_session: AsyncSession, fake_redis: object) -> AsyncIterator[str]:
    from cti_api.deps import get_db, get_redis
    from cti_api.main import create_app

    app = create_app()

    async def _db() -> AsyncIterator[AsyncSession]:
        yield api_session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = lambda: fake_redis
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


def _read(url: str, token: str) -> tuple[list[str], list[str]]:
    srv = Server(f"{url}/taxii2/", user="client", password=token)
    root = srv.default or srv.api_roots[0]
    col = root.collections[0]

    def ids(fetch: object, key: str) -> list[str]:
        return [o["id"] for p in as_pages(fetch, per_request=2) for o in p.get(key, [])]

    manifest = ids(col.get_manifest, "objects")
    objs = ids(col.get_objects, "objects")
    return manifest, objs


async def test_taxii2_client_reads_collection(
    base_url: str, api_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(feed, "FEED_SETTLE_SECONDS", 0)
    base = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    expected = []
    for i in range(5):
        value = f"interop{i}.example.com"
        api_session.add(
            Indicator(
                type="domain",
                value=value,
                stix_id=indicator_uuid("domain", value),
                feed_changed_at=base + datetime.timedelta(seconds=i),
            )
        )
        expected.append(f"indicator--{indicator_uuid('domain', value)}")
    token = machine_auth.generate_token()
    await AsyncApiTokenRepo(api_session).create(
        name="interop",
        token_prefix=token[:8],
        token_hash=machine_auth.hash_token(token),
        scopes=["indicators:read"],
        max_tlp="red",
        created_by="tester",
        expires_at=None,
    )
    await api_session.flush()

    manifest, objs = await asyncio.to_thread(_read, base_url, token)
    assert sorted(manifest) == sorted(expected)
    assert sorted(objs) == sorted(expected)
