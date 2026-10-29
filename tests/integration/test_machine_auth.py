import base64
import datetime
from typing import Annotated

import httpx
import pytest
from cti_api.deps import get_db
from cti_api.machine_auth import MachinePrincipal, generate_token, hash_token, require_token
from cti_core.db.repositories.auth import AsyncApiTokenRepo
from fastapi import Depends, FastAPI
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def _make(session, *, scopes=("indicators:read",), expires_at=None):
    token = generate_token()
    row = await AsyncApiTokenRepo(session).create(
        name="splunk",
        token_prefix=token[:8],
        token_hash=hash_token(token),
        scopes=list(scopes),
        max_tlp="amber",
        created_by="admin",
        expires_at=expires_at,
    )
    return token, row


def _client(session):
    app = FastAPI()

    @app.get("/probe")
    async def probe(p: Annotated[MachinePrincipal, Depends(require_token("indicators:read"))]):
        return {"name": p.name, "max_tlp": p.max_tlp}

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _basic(user: str, token: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()


async def test_bearer_ok(api_session):
    token, _ = await _make(api_session)
    async with _client(api_session) as c:
        r = await c.get("/probe", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json() == {"name": "splunk", "max_tlp": "amber"}


async def test_basic_ok(api_session):
    token, _ = await _make(api_session)
    async with _client(api_session) as c:
        r = await c.get("/probe", headers={"Authorization": _basic("splunk", token)})
    assert r.status_code == 200


async def test_basic_empty_username_ok(api_session):
    token, _ = await _make(api_session)
    async with _client(api_session) as c:
        r = await c.get("/probe", headers={"Authorization": _basic("", token)})
    assert r.status_code == 200


async def test_unknown_token_401_with_www_authenticate(api_session):
    async with _client(api_session) as c:
        r = await c.get("/probe", headers={"Authorization": "Bearer vrn_unknown"})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == 'Basic realm="vareon", Bearer'
    assert r.json()["detail"] == "Invalid or missing API token"


async def test_expired_token_401(api_session):
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
    token, _ = await _make(api_session, expires_at=past)
    async with _client(api_session) as c:
        r = await c.get("/probe", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_revoked_token_401_immediately(api_session):
    token, row = await _make(api_session)
    h = {"Authorization": f"Bearer {token}"}
    async with _client(api_session) as c:
        assert (await c.get("/probe", headers=h)).status_code == 200
        await AsyncApiTokenRepo(api_session).revoke(row, by="admin")
        assert (await c.get("/probe", headers=h)).status_code == 401


async def test_wrong_scope_403(api_session):
    token, _ = await _make(api_session, scopes=())
    async with _client(api_session) as c:
        r = await c.get("/probe", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert r.json()["detail"] == "Token lacks scope: indicators:read"


@pytest.mark.parametrize(
    "header",
    [
        "Bearer",
        "Bearer abc",
        "Basic !!!",
        "Basic " + base64.b64encode(b"user").decode(),
        "Basic " + base64.b64encode(b"\xff\xfe:x").decode(),
        "Token vrn_x",
        "Bearer vrn_x ",
        "",
    ],
)
async def test_malformed_credentials_401(api_session, header):
    async with _client(api_session) as c:
        r = await c.get("/probe", headers={"Authorization": header})
    assert r.status_code == 401


async def test_missing_header_401(api_session):
    async with _client(api_session) as c:
        assert (await c.get("/probe")).status_code == 401


async def test_last_used_throttled(api_session):
    token, row = await _make(api_session)
    h = {"Authorization": f"Bearer {token}"}

    async def last():
        return (
            await api_session.execute(
                text("SELECT last_used_at FROM api_tokens WHERE id = :i"), {"i": row.id}
            )
        ).scalar_one()

    async with _client(api_session) as c:
        await c.get("/probe", headers=h)
        first = await last()
        assert first is not None
        await c.get("/probe", headers=h)
        assert await last() == first  # < 60 s: tidak ditulis ulang
        await api_session.execute(
            text("UPDATE api_tokens SET last_used_at = now() - interval '2 minutes' WHERE id = :i"),
            {"i": row.id},
        )
        old = await last()
        await c.get("/probe", headers=h)
        assert await last() > old  # lewat 60 s: ditulis ulang
