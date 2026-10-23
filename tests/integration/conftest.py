"""Fixture Postgres buat test integrasi -- testcontainers nyalain container
EFEMERAL sendiri (beda dari container docker-compose yang dipakai manual
waktu dev), supaya CI bisa jalanin ini tanpa setup tambahan apa pun.

Scope "session": satu container buat semua test integrasi dalam satu run
pytest -- nyalain Postgres ~2 detik, jangan diulang per test.
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import pytest
import redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        sync_url = pg.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+psycopg://"
        )
        yield sync_url


@pytest.fixture(scope="session")
def redis_client() -> Iterator[redis.Redis]:
    """Redis EFEMERAL beneran (bukan fake) -- dipakai test yang semantiknya
    justru Redis-spesifik: lock beat (`SET NX PX` + Lua) dan kedalaman antrian
    Celery (`LLEN`). Scope "session": satu container, tiap test yang butuh
    bersih-bersih sendiri (`flushall`)."""
    from testcontainers.community.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as rc:
        yield rc.get_client()


@pytest.fixture(scope="package")
def _configured_settings(postgres_url: str) -> Iterator[None]:
    """Arahin cti_core.config ke Postgres efemeral.

    Scope "package" (BUKAN "session") disengaja: fixture ini ngubah
    `os.environ` GLOBAL (AUTH__JWT_SECRET dkk). Kalau di-scope "session",
    teardown-nya baru jalan di akhir SELURUH pytest run -- kalau
    `tests/integration/` kebetulan jalan sebelum `tests/unit/` (urutan
    alfabetis: "integration" < "unit"), env var bocor ke test lain dan
    bikin `test_missing_required_secret_fails_loud` di test_config.py
    gagal karena AUTH__JWT_SECRET udah keisi "test-secret" dari sini.
    Ketauan dari full-suite run, bukan dugaan -- lihat commit message."""
    async_url = postgres_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    env = {
        "DATABASE__URL": async_url,
        "DATABASE__SYNC_URL": postgres_url,
        "AUTH__JWT_SECRET": "test-secret",
        "AUTH__SESSION_SECRET_KEY": "test-session",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)

    from cti_core.config import get_settings
    from cti_core.db.engine import reset_engines

    get_settings.cache_clear()
    reset_engines()

    yield

    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()
    reset_engines()


@pytest.fixture(scope="package")
def _migrated_schema(_configured_settings: None) -> Iterator[None]:
    """`alembic upgrade head` beneran, sama persis yang dijalanin di
    deployment (bukan `Base.metadata.create_all()` -- itu gak nguji migrasi
    yang sesungguhnya dipakai buat naikin skema di produksi).

    Scope "package" ngikutin _configured_settings -- pytest nolak fixture
    "session" yang depend ke fixture "package" (lebih sempit)."""
    from alembic.config import Config

    from alembic import command

    root = _find_repo_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")

    yield

    command.downgrade(cfg, "base")


def _find_repo_root() -> pathlib.Path:
    p = pathlib.Path(__file__).resolve()
    while not (p / "alembic.ini").exists():
        if p.parent == p:
            raise RuntimeError("alembic.ini gak ketemu di parent mana pun")
        p = p.parent
    return p


@pytest.fixture
def db_session(_migrated_schema: None) -> Iterator[Session]:
    """Sesi sync per-test, di-rollback di akhir -- satu test gak
    kecemar hasil test lain."""
    from cti_core.db.engine import get_sync_engine

    engine = get_sync_engine()
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
async def async_db_session(_migrated_schema: None) -> AsyncIterator[AsyncSession]:
    from cti_core.db.engine import get_async_engine

    engine = get_async_engine()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def api_session(_migrated_schema: None) -> AsyncIterator[AsyncSession]:
    """Varian `async_db_session` khusus test lewat HTTP (`api_client`
    di bawah) -- handler router SERING manggil `session.commit()` sendiri
    (pola "unit of work per request", beda dari test service-layer yang
    cuma numpang `session.flush()`). `AsyncSession(bind=connection)` polos
    bakal KETUTUP BENERAN kena `commit()` dari app code -- `transaction.
    rollback()` pas teardown jadi gak ngefek, data leak ke Postgres
    efemeral yang dipakai bareng semua test lain dalam run ini.

    Fix: `join_transaction_mode="create_savepoint"` (SQLAlchemy 2.0,
    recipe resmi buat "joining a session into an external transaction").
    `commit()` dari app code cuma nutup SAVEPOINT internal, transaksi luar
    (yang di-rollback pas teardown di sini) tetep idup -- isolasi antar
    test tetep kejaga walau endpoint yang dites beneran commit.

    `expire_on_commit=False` WAJIB -- production (`cti_core.db.engine.
    _async_sessionmaker()`) udah pasang ini eksplisit (router pola umum:
    akses attribute objek abis `session.commit()`, mis. `entry.id` di
    `iocs.py`'s `ioc_allowlist_add`). Default SQLAlchemy (`True`) bikin
    attribute EXPIRE abis commit -- akses berikutnya trigger lazy-reload
    yang butuh jembatan async/greenlet, dan itu KETUBRUK event listener
    auto-restart-savepoint di atas (`MissingGreenlet` -- ketauan lewat
    reproduksi langsung, bukan dugaan). Fixture ini WAJIB nge-mirror
    config production, bukan cuma soal SQLAlchemy internals."""
    from cti_core.db.engine import get_async_engine

    engine = get_async_engine()
    async with engine.connect() as connection:
        await connection.begin()
        session = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await connection.rollback()


class _FakeRedis:
    """Redis in-memory MINIMAL -- cuma `incr`/`expire` (dipakai
    `is_rate_limited()`, `rate_limit.py`). `api_client` gak numpang
    testcontainer Redis beneran (beda dari Postgres) -- satu-satunya
    pemakai saat ini (`POST /api/auth/login`'s rate limit) gak butuh
    semantik Redis penuh, dan ini ngejaga suite tetep jalan tanpa Redis
    server apa pun (CI-friendly, sama filosofi container efemeral
    Postgres di atas)."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._ttl: dict[str, int] = {}
        self.values: dict[str, str] = {}
        """`get` -- heartbeat beat (`GET /api/scraper`); test isi langsung lewat
        `fake_redis.values[...]`."""
        self.lists: dict[str, int] = {}
        """`llen` -- panjang list per kunci, diisi langsung oleh test."""

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def llen(self, key: str) -> int:
        """Panjang list (antrian Celery `enrich` di `/api/data-health`); test isi lewat `lists`."""
        return self.lists.get(key, 0)

    async def incr(self, key: str) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def set(self, key: str, value: int, *, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self._counts:
            return False
        self._counts[key] = int(value)
        if ex is not None:
            self._ttl[key] = ex
        return True

    async def ttl(self, key: str) -> int:
        """Sisa umur kunci; fake ini tidak menjalankan waktu: = `ex` terakhir, -2 bila tak ada."""
        return self._ttl.get(key, -2) if key in self._counts else -2

    async def delete(self, key: str) -> int:
        self._ttl.pop(key, None)
        return 1 if self._counts.pop(key, None) is not None else 0

    async def mget(self, *keys: str) -> list[int | None]:
        return [self._counts.get(k) for k in keys]

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self)


class _FakePipeline:
    """`async with redis.pipeline()`: antrikan `set`/`incr`, `execute()` jalankan berurutan."""

    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def __aenter__(self) -> _FakePipeline:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def set(self, *args: Any, **kwargs: Any) -> None:
        self._ops.append(("set", args, kwargs))

    def incr(self, *args: Any, **kwargs: Any) -> None:
        self._ops.append(("incr", args, kwargs))

    async def execute(self) -> list[Any]:
        return [await getattr(self._redis, name)(*a, **kw) for name, a, kw in self._ops]


@pytest.fixture
def fake_redis() -> _FakeRedis:
    """Instance yang SAMA dengan yang di-inject `api_client` lewat `get_redis` --
    test yang butuh isi key (mis. heartbeat beat) nulis ke `fake_redis.values`."""
    return _FakeRedis()


@pytest.fixture
async def api_client(
    api_session: AsyncSession, fake_redis: _FakeRedis
) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client ASGI langsung ke `create_app()` -- request beneran
    lewat routing/dependency-injection/response_model serialization
    FastAPI (bukan manggil fungsi service langsung kayak test lain), tapi
    `get_db` di-override numpang `api_session` (isolasi transaksi per-test
    tetep kejaga, lihat docstring fixture itu), `get_redis` di-override
    `_FakeRedis` (lihat docstring kelas itu).

    Lifespan `create_app()` (`ensure_default()`/`ensure_system_roles()`)
    SENGAJA gak jalan -- `httpx.ASGITransport` gak ngirim event
    lifespan startup/shutdown kayak server ASGI beneran. Client "default"
    di-ensure manual di sini pake `api_session` yang sama (paling umum
    dibutuhin endpoint multi-tenant); test yang butuh system roles
    (`ensure_system_roles`) panggil sendiri kalau perlu."""
    from cti_api.deps import get_db, get_redis
    from cti_api.main import create_app
    from cti_core.db.repositories.auth import AsyncClientRepo

    await AsyncClientRepo(api_session).ensure_default()

    app = create_app()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield api_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = lambda: fake_redis
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_header() -> Callable[..., dict[str, str]]:
    """Factory `dict` header `Authorization: Bearer <jwt>` -- JWT ASLI
    lewat `create_token()` (bukan override dependency auth), jadi jalur
    `decode_token()`/`get_current_user()` beneran kepake, gak di-skip."""

    def _make(
        username: str = "tester", role: str = "superadmin", client_ids: list[str] | None = None
    ) -> dict[str, str]:
        from cti_api.security import create_token

        token = create_token(username, role, client_ids or ["default"])
        return {"Authorization": f"Bearer {token}"}

    return _make


@pytest.fixture(autouse=True)
def _clear_in_process_caches() -> None:
    """6 service (`cluster`/`article_dashboard`/`risk_matrix`/
    `fp_analytics`/`spike`/`d3fend`) punya cache module-level (900s TTL,
    key dari parameter query kayak `days`/`threshold`) -- didesain buat
    ngirit query di PRODUKSI (satu proses long-lived), tapi di TEST jadi
    sumber flaky: dua test beda yang manggil endpoint sama dengan
    parameter default sama (mis. `days=30`) bakal SALING numpang hasil
    cache, walau masing-masing seed data DB-nya beda (ketauan lewat full-
    suite run: `test_build_cluster_mindmap_stats_branch_populated` dan
    beberapa snapshot test Fase 7.6 saling ganggu gara-gara ini -- bukan
    hipotesis, kejadian beneran). Autouse (bukan manual per-test) biar
    proteksinya nutup SEMUA test integrasi, bukan cuma yang inget clear
    manual -- lebih murah dari nebak-nebak titik mana yang butuh."""
    from cti_api.services import (
        article_dashboard,
        cluster,
        d3fend,
        data_health,
        fp_analytics,
        risk_matrix,
        spike,
        trending,
    )

    cluster._CACHE.clear()
    article_dashboard._dashboard_cache.clear()
    risk_matrix._CACHE.clear()
    fp_analytics._fp_analytics_cache = None
    spike._CACHE.clear()
    trending._CACHE.clear()
    d3fend._cache.clear()
    data_health._cache = None


@pytest.fixture(autouse=True)
def _skip_if_docker_unavailable() -> None:
    """Testcontainers butuh Docker daemon. Kalau gak ada, skip jelas --
    bukan error yang bikin bingung."""
    import shutil
    import subprocess

    if not shutil.which("docker"):
        pytest.skip("butuh Docker buat test integrasi")
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=5, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pytest.skip("Docker daemon gak jalan")
