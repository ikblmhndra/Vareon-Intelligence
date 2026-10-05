"""Regresi QA 2026-10-05 yang bisa dicek tanpa Postgres."""

from cti_core.db.models.article import RejectedArticle
from sqlalchemy.dialects import postgresql


def test_rejected_article_punya_raw_enrichment():
    row = RejectedArticle(url="u", url_hash="h", title="t", source="s", raw_enrichment={"a": 1})
    assert row.raw_enrichment == {"a": 1}


def test_migrasi_rejected_raw_enrichment_menyambung_ke_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    assert heads == ["d7b1f3a9c2e5"]


class _FakeResult:
    def scalar_one(self):
        return 0

    def scalars(self):
        return self

    def all(self):
        return []


class _FakeSession:
    def __init__(self):
        self.stmts = []

    async def execute(self, stmt):
        self.stmts.append(stmt)
        return _FakeResult()


async def test_cve_list_filtered_order_punya_tiebreaker_id():
    from cti_core.db.repositories.cve import AsyncCveTrackerRepo

    session = _FakeSession()
    await AsyncCveTrackerRepo(session).list_filtered(client_id="c")
    sql = str(session.stmts[-1].compile(dialect=postgresql.dialect()))
    order_by = sql.split("ORDER BY")[1].split("LIMIT")[0]
    assert "cve_tracker.id" in order_by


def test_email_env_escape_html_dan_blokir_url_non_http():
    from cti_api.services.email_env import http_url, make_env

    env = make_env(".")
    out = env.from_string("{{ t }}|{{ h | safe }}|{{ u | http_url }}").render(
        t="<img src=x onerror=1>", h="<b>ok</b>", u="javascript:alert(1)"
    )
    assert out == "&lt;img src=x onerror=1&gt;|<b>ok</b>|#"
    assert http_url("https://a.b/c") == "https://a.b/c"
    assert http_url("data:text/html,x") == "#"


def test_ensure_client_access():
    import pytest
    from cti_api.deps import ensure_client_access
    from fastapi import HTTPException

    ensure_client_access({"username": "u", "role": "analyst", "client_ids": ["a"]}, "a")
    ensure_client_access({"username": "s", "role": "superadmin", "client_ids": ["a"]}, "zzz")
    with pytest.raises(HTTPException) as e:
        ensure_client_access({"username": "u", "role": "admin", "client_ids": ["a"]}, "b")
    assert e.value.status_code == 404


def test_endpoint_baca_wajib_auth(monkeypatch):
    """Tanpa token -> 401 (bukan 200/500) untuk router yang dulu terbuka."""
    from cti_core.config import get_settings
    from fastapi.testclient import TestClient

    for key, value in {
        "DATABASE__URL": "postgresql+asyncpg://x:x@localhost/x",
        "DATABASE__SYNC_URL": "postgresql+psycopg://x:x@localhost/x",
        "AUTH__JWT_SECRET": "unit-test-jwt-secret",
        "AUTH__SESSION_SECRET_KEY": "unit-test-session-secret",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()

    from cti_api.main import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    for path in (
        "/api/articles",
        "/api/filtered-articles",
        "/api/pir/options",
        "/api/pir/1/export",
        "/api/sr/entries",
        "/api/ta/groups",
        "/api/ta/profile/x",
        "/api/stix/iocs",
        "/api/exec/dashboard",
        "/api/newsletter/source-hints",
    ):
        assert client.get(path).status_code == 401, path


async def test_rate_limit_atomik_dan_memblokir_setelah_batas():
    from cti_api.rate_limit import is_rate_limited

    class _Pipe:
        def __init__(self, store):
            self.store, self.ops = store, []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        def set(self, key, value, ex=None, nx=False):
            self.ops.append(("set", key, value, ex, nx))

        def incr(self, key):
            self.ops.append(("incr", key))

        async def execute(self):
            out = []
            for op in self.ops:
                if op[0] == "set":
                    _, key, value, ex, nx = op
                    assert ex == 60 and nx is True  # TTL selalu dipasang bersama key
                    if not (nx and key in self.store):
                        self.store[key] = value
                    out.append(True)
                else:
                    self.store[op[1]] += 1
                    out.append(self.store[op[1]])
            return out

    class _Redis:
        def __init__(self):
            self.store = {}

        def pipeline(self, transaction=True):
            return _Pipe(self.store)

    r = _Redis()
    hasil = [await is_rate_limited(r, "k", max_requests=3, window_seconds=60) for _ in range(5)]
    assert hasil == [False, False, False, True, True]


class _KvRedis:
    """Redis minimal untuk pencabutan token: set/mget."""

    def __init__(self):
        self.kv = {}

    async def set(self, key, value, ex=None, nx=False):
        self.kv[key] = value
        return True

    async def mget(self, *keys):
        return [self.kv.get(k) for k in keys]


def _auth_app(monkeypatch, redis):
    from cti_core.config import get_settings
    from fastapi import Depends, FastAPI

    for key, value in {
        "DATABASE__URL": "postgresql+asyncpg://x:x@localhost/x",
        "DATABASE__SYNC_URL": "postgresql+psycopg://x:x@localhost/x",
        "AUTH__JWT_SECRET": "unit-test-jwt-secret",
        "AUTH__SESSION_SECRET_KEY": "unit-test-session-secret",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()

    from cti_api.deps import get_redis, require_auth

    app = FastAPI()

    @app.get("/api/x")
    async def x(user=Depends(require_auth)):  # noqa: B008
        return {"u": user["username"]}

    @app.get("/api/auth/me")
    async def me(user=Depends(require_auth)):  # noqa: B008
        return {"u": user["username"], "fpc": user["force_pw_change"]}

    app.dependency_overrides[get_redis] = lambda: redis
    return app


def test_token_dicabut_setelah_revoke_user(monkeypatch):
    import asyncio
    import time

    from cti_api.security import create_token
    from cti_api.token_revocation import revoke_user_tokens
    from fastapi.testclient import TestClient

    redis = _KvRedis()
    client = TestClient(_auth_app(monkeypatch, redis))
    token = create_token("alice", "analyst")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/x", headers=headers).status_code == 200
    asyncio.run(revoke_user_tokens(redis, "alice"))
    assert client.get("/api/x", headers=headers).status_code == 401
    time.sleep(1.1)  # token baru (iat lebih baru dari waktu pencabutan) harus diterima
    fresh = {"Authorization": f"Bearer {create_token('alice', 'analyst')}"}
    assert client.get("/api/x", headers=fresh).status_code == 200


def test_force_pw_change_hanya_boleh_endpoint_tertentu(monkeypatch):
    from cti_api.security import create_token
    from fastapi.testclient import TestClient

    client = TestClient(_auth_app(monkeypatch, _KvRedis()))
    headers = {"Authorization": f"Bearer {create_token('bob', 'analyst', force_pw_change=True)}"}
    blocked = client.get("/api/x", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Password change required"
    ok = client.get("/api/auth/me", headers=headers)
    assert ok.status_code == 200 and ok.json()["fpc"] is True
