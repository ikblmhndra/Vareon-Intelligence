"""Bahan bersama tes router `/api/secrets` (ROADMAP #23, PR 2): lingkungan `.env` palsu, probe
palsu, jembatan overlay, dan pembantu baca/tulis DB lewat `api_session`.

Tiga keputusan yang perlu dijelaskan:

- `Settings` dibaca dari ENV (`monkeypatch`-style + `get_settings.cache_clear()`), bukan di-patch:
  jalur yang dites sama dengan produksi (master key, `environment`, allowlist, key `.env` semuanya
  datang dari satu `get_settings()`). Semua key provider diisi (`ENV_VALUES`) supaya "key .env tidak
  bocor ke response" benar-benar dibuktikan, dan env host pengembang tidak ikut campur.
- Overlay (`effective_settings()`) membaca DB lewat `sync_session()`: koneksi lain, tidak melihat
  baris yang belum commit di transaksi tes (`api_session` di-rollback di akhir). `OverlayRows`
  menggantikan `overlay._fetch_rows` dengan baris yang sama persis seperti yang ada di
  `api_session`; `Ctx.seed()` mengisinya otomatis, dan sesudah PUT/DELETE tes memanggil
  `Ctx.sync_overlay()` SENDIRI (tanpa invalidate) supaya terbukti router-lah yang membuang cache.
- Probe diganti `FakeProbe` di `cti_api.services.runtime_secrets.run_probe` (titik yang dijanjikan
  kontrak): tidak ada HTTP, dan tes bisa mengatur hasilnya serta mencatat `Settings` yang diterima.

- `POST /{provider}/test` me-rollback sesi sebelum probe (probe bisa berdetik-detik), dan di tes
  `api_session` dipakai bersama: baris yang cuma di-flush ikut terbuang. Karena itu `Ctx.seed()`
  COMMIT (savepoint dilepas ke transaksi luar, yang tetap di-rollback di akhir tes).
- `_FakeRedis.get` bawaan `conftest.py` hanya membaca `values`, sedangkan lockout password membaca
  penghitung (`failures:pw:<user>`) yang ditulis lewat `incr`; `open_ctx` memasang `get` yang
  membaca keduanya, seperti Redis sungguhan (`conftest.py` dibiarkan, dipakai tes lain).

Password uji: hash bcrypt dibuat dengan `rounds=4` (verifikasi ~1 ms, bukan ~250 ms); hash itu sah
buat `verify_password` karena parameter biayanya ikut tertanam di hash.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import bcrypt
import pytest
from cti_core.config import Settings, get_settings
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.runtime_secret import RuntimeSecret
from cti_core.db.repositories.auth import AsyncUserRepo
from cti_core.runtime_secrets import overlay
from cti_core.runtime_secrets.crypto import decrypt_fields, encrypt_fields
from httpx import AsyncClient, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.runtime_secrets_helpers import ENV_VALUES, KEYS, NON_SECRET_VALUES, OTHER_KEYS

PASSWORD = "P@ssw0rd123"
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
ROOT = "root"

ENTRY_KEYS = {
    "key",
    "label",
    "source",
    "fields",
    "updated_by",
    "updated_at",
    "last_test_ok",
    "last_test_at",
    "error",
    "probe",
}
FIELD_KEYS = {"name", "secret", "source", "value", "last4", "choices"}

# key (palsu) yang dipasang lewat API/DB; ekor unik supaya `last4` bisa dibedakan dari nilai .env
# (semua nilai .env di `ENV_VALUES` berakhiran "aaaa").
NEW_NVD = "nvd-new-key-aaaaaa-Q7w2"  # gitleaks:allow
OLD_NVD = "nvd-old-key-bbbbbb-M3k8"  # gitleaks:allow
NEW_LLM_KEY = "sk-new-llm-key-aaaaaa-Zk81"  # gitleaks:allow
OLD_LLM_KEY = "sk-old-llm-key-bbbbbb-Hp40"  # gitleaks:allow
LLM_BUNDLE = {
    "api_key": NEW_LLM_KEY,
    "provider": "deepseek",
    "model": "deepseek-chat",
    "url": "",
}
OLD_LLM_BUNDLE = {
    "api_key": OLD_LLM_KEY,
    "provider": "openai",
    "model": "model-old-bbbbbb",
    "url": "",
}


def env_name(provider: str, field: str) -> str:
    return f"{provider}__{field}".upper()


BASE_ENV: dict[str, str] = {
    "ENVIRONMENT": "dev",
    "SECRETS_ENCRYPTION_KEYS": KEYS,
    "SECRETS_LLM_URL_ALLOWED_HOSTS": "",
    "LLM__PROVIDER": "openai",
    "LLM__MODEL": NON_SECRET_VALUES["llm_model"],
    "LLM__URL": NON_SECRET_VALUES["llm_url"],
    **{env_name(p, f): v for (p, f), v in ENV_VALUES.items()},
}


@contextmanager
def secrets_environment() -> Iterator[Callable[..., None]]:
    """`.env` palsu (`BASE_ENV`) aktif selama blok ini; yield fungsi `configure(**env)` buat
    mengubah/menambah variabel di tengah tes. Cache `get_settings()` dan overlay dibuang setiap
    kali env berubah dan sekali lagi sesudah env dikembalikan."""
    with pytest.MonkeyPatch.context() as mp:

        def configure(**env: str) -> None:
            for name, value in env.items():
                mp.setenv(name, value)
            get_settings.cache_clear()
            overlay.invalidate()

        configure(**BASE_ENV)
        try:
            yield configure
        finally:
            mp.undo()
            get_settings.cache_clear()
            overlay.invalidate()


class FakeProbe:
    """Pengganti `run_probe`: hasilnya diatur lewat `respond`, panggilannya dicatat."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Settings]] = []
        self.hook: Callable[[str, Settings], Awaitable[None]] | None = None
        self._status = "OK"
        self._detail = "probe palsu"

    def respond(self, status: str, detail: str = "probe palsu") -> None:
        self._status, self._detail = status, detail

    async def __call__(self, provider: str, settings: Settings, *, timeout: float = 15.0) -> Any:
        from cti_api.services.secret_probes import Result

        self.calls.append((provider, settings))
        if self.hook is not None:
            await self.hook(provider, settings)
        return Result(provider, self._status, self._detail)


class OverlayRows:
    """Isi `overlay._fetch_rows` di tes: baris platform seperti yang terlihat di `api_session`."""

    def __init__(self) -> None:
        self.rows: list[Any] = []

    def __call__(self) -> list[Any]:
        return list(self.rows)


@dataclass
class Ctx:
    client: AsyncClient
    session: AsyncSession
    configure: Callable[..., None]
    probe: FakeProbe
    overlay_rows: OverlayRows
    auth_header: Callable[..., dict[str, str]]
    fake_redis: Any = None
    raw_commit: Callable[[], Awaitable[None]] | None = None
    commits: int = 0
    """Berapa kali handler memanggil `session.commit()`. `api_session` dipakai bersama tes, jadi
    baris yang cuma di-flush (lalu hilang bersama request di produksi) tetap terlihat di tes;
    jumlah commit adalah satu-satunya cara membuktikan perubahan/audit benar-benar durable."""

    @property
    def auth(self) -> dict[str, str]:
        return self.auth_header(username=ROOT, role="superadmin")

    def headers(self, username: str, role: str = "superadmin") -> dict[str, str]:
        return self.auth_header(username=username, role=role)

    # --- HTTP ---------------------------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return await self.client.request(
            method, path, json=body, headers=self.auth if headers is None else headers
        )

    async def get(self, *, headers: dict[str, str] | None = None) -> Response:
        return await self.request("GET", "/api/secrets", headers=headers)

    async def put(
        self,
        provider: str,
        fields: dict[str, Any],
        *,
        password: str = PASSWORD,
        headers: dict[str, str] | None = None,
    ) -> Response:
        body = {"fields": fields, "current_password": password}
        return await self.request("PUT", f"/api/secrets/{provider}", body, headers=headers)

    async def delete(
        self, provider: str, *, password: str = PASSWORD, headers: dict[str, str] | None = None
    ) -> Response:
        body = {"current_password": password}
        return await self.request("DELETE", f"/api/secrets/{provider}", body, headers=headers)

    async def run_test(self, provider: str, *, headers: dict[str, str] | None = None) -> Response:
        return await self.request("POST", f"/api/secrets/{provider}/test", headers=headers)

    async def entry(self, provider: str) -> dict[str, Any]:
        """Entri provider itu dari `GET /api/secrets`."""
        resp = await self.get()
        assert resp.status_code == 200
        return next(p for p in resp.json()["providers"] if p["key"] == provider)

    async def headers_after_revocation(self, username: str = ROOT) -> dict[str, str]:
        """Token BARU sesudah token user dicabut. Pencabutan membandingkan `iat` (detik) dengan
        waktu pencabutan dengan `<=`, jadi token yang dibuat di detik yang sama ikut tercabut:
        tunggu detik berikutnya dulu."""
        await asyncio.sleep(1.1)
        return self.headers(username)

    def reset_write_budget(self, username: str = ROOT) -> None:
        """Kosongkan jatah 5 tulis/menit (`ratelimit:secrets:write:<user>`) supaya tes lockout
        password tidak tertutup 429 dari rate limit biasa."""
        self.fake_redis._counts.pop(f"ratelimit:secrets:write:{username}", None)

    async def revoked_at(self, username: str = ROOT) -> int | None:
        """Waktu pencabutan semua token user (`revoked_user:<user>`), None kalau belum dicabut."""
        (value,) = await self.fake_redis.mget(f"revoked_user:{username}")
        return value

    # --- DB -----------------------------------------------------------------------------------

    async def add_user(
        self, username: str, *, role: str = "superadmin", password_hash: str = PASSWORD_HASH
    ) -> None:
        from cti_api.services.roles import ensure_system_roles

        await ensure_system_roles(self.session)
        await AsyncUserRepo(self.session).create(
            username=username, password_hash=password_hash, role_name=role, client_ids=["default"]
        )

    async def row(self, provider: str) -> RuntimeSecret | None:
        stmt = (
            select(RuntimeSecret)
            .where(RuntimeSecret.provider == provider, RuntimeSecret.client_id.is_(None))
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def stored(self, provider: str) -> dict[str, str] | None:
        """Isi override yang tersimpan (didekripsi dengan master key tes), None kalau tak ada."""
        row = await self.row(provider)
        if row is None:
            return None
        return decrypt_fields(provider, bytes(row.secrets_enc), keys=KEYS)

    async def raw_row_text(self, provider: str) -> str:
        """Seluruh baris sebagai teks Postgres (bytea tampil sebagai hex)."""
        stmt = text("SELECT t::text FROM runtime_secrets t WHERE provider = :p")
        return str((await self.session.execute(stmt, {"p": provider})).scalar_one())

    async def count_rows(self) -> int:
        stmt = select(RuntimeSecret).where(RuntimeSecret.client_id.is_(None))
        return len((await self.session.execute(stmt)).scalars().all())

    async def seed(
        self,
        provider: str,
        fields: dict[str, str] | None = None,
        *,
        updated_by: str = "seeder",
        keys: str = KEYS,
        last_test_ok: bool | None = None,
        last_test_at: Any = None,
    ) -> RuntimeSecret:
        """Baris override yang SAH (terenkripsi dengan `keys`), terlihat juga oleh overlay."""
        row = RuntimeSecret(
            provider=provider,
            secrets_enc=encrypt_fields(provider, fields or {"api_key": OLD_NVD}, keys=keys),
            updated_by=updated_by,
            last_test_ok=last_test_ok,
            last_test_at=last_test_at,
        )
        self.session.add(row)
        await self.session.flush()
        assert self.raw_commit is not None
        await self.raw_commit()  # lihat docstring modul: endpoint test me-rollback sesi
        await self.sync_overlay()
        overlay.invalidate()
        return row

    async def seed_unreadable(self, provider: str) -> None:
        """Baris yang tidak bisa didekripsi master key yang sekarang (dienkripsi kunci lain)."""
        await self.seed(provider, {"api_key": "fake-unreadable-key-0004"}, keys=OTHER_KEYS)

    async def sync_overlay(self) -> None:
        """Samakan baris yang terlihat overlay dengan isi `api_session` SEKARANG. TIDAK membuang
        cache overlay: itu tugas router (dan itulah yang dibuktikan tes invalidate)."""
        stmt = (
            select(RuntimeSecret)
            .where(RuntimeSecret.client_id.is_(None))
            .execution_options(populate_existing=True)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        self.overlay_rows.rows = [
            SimpleNamespace(
                provider=r.provider, client_id=r.client_id, secrets_enc=bytes(r.secrets_enc)
            )
            for r in rows
        ]

    async def audit(self, action: str) -> list[AuditLogEntry]:
        stmt = (
            select(AuditLogEntry)
            .where(AuditLogEntry.action == action)
            .order_by(AuditLogEntry.id)
            .execution_options(populate_existing=True)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def audit_text(self, action: str) -> str:
        """Semua kolom baris audit `action`, sebagai satu teks JSON (buat cek 'tidak ada nilai')."""
        return json.dumps(
            [
                {
                    "username": e.username,
                    "action": e.action,
                    "target_id": e.target_id,
                    "detail": e.detail,
                    "ip_address": e.ip_address,
                }
                for e in await self.audit(action)
            ]
        )


@asynccontextmanager
async def open_ctx(
    client: AsyncClient,
    session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: Any,
) -> AsyncIterator[Ctx]:
    probe = FakeProbe()
    overlay_rows = OverlayRows()
    monkeypatch.setattr("cti_api.services.runtime_secrets.run_probe", probe)
    monkeypatch.setattr(overlay, "_fetch_rows", overlay_rows)
    with secrets_environment() as configure:
        ctx = Ctx(client, session, configure, probe, overlay_rows, auth_header, fake_redis)
        await ctx.add_user(ROOT)
        original_commit = session.commit
        ctx.raw_commit = original_commit

        async def faithful_get(key: str) -> str | None:
            if key in fake_redis.values:
                return str(fake_redis.values[key])
            if key in fake_redis._counts:
                return str(fake_redis._counts[key])
            return None

        monkeypatch.setattr(fake_redis, "get", faithful_get)

        async def counting_commit() -> None:
            ctx.commits += 1
            await original_commit()

        monkeypatch.setattr(session, "commit", counting_commit)
        yield ctx


def assert_no_value(text_: str, *values: str) -> None:
    """Tak satu pun nilai ada di teks. Nilainya palsu, jadi aman muncul di pesan kegagalan."""
    for value in values:
        assert value not in text_, f"nilai secret muncul: {value}"
