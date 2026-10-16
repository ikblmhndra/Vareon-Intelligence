"""Repo `runtime_secrets` (ROADMAP #23): `RuntimeSecretRepo` (sync, baca) dipakai overlay di proses
sync (Celery/CLI) dan API lewat `sync_session()`; `AsyncRuntimeSecretRepo` (async, baca + tulis)
dipakai endpoint admin. Semuanya hanya menyentuh scope platform (`client_id IS NULL`): baris
per-workspace belum ditulis siapa pun di irisan ini, dan tidak boleh ikut terhapus/tertimpa oleh
jalur platform.
"""

from __future__ import annotations

import datetime
from typing import Any, cast

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.models.runtime_secret import RuntimeSecret


class RuntimeSecretRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_platform(self) -> list[RuntimeSecret]:
        """Baris scope platform (`client_id IS NULL`), urut provider biar hasilnya deterministik."""
        stmt = (
            select(RuntimeSecret)
            .where(RuntimeSecret.client_id.is_(None))
            .order_by(RuntimeSecret.provider)
        )
        return list(self.session.scalars(stmt).all())


class AsyncRuntimeSecretRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_platform(self) -> list[RuntimeSecret]:
        stmt = (
            select(RuntimeSecret)
            .where(RuntimeSecret.client_id.is_(None))
            .order_by(RuntimeSecret.provider)
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_platform(self, provider: str) -> RuntimeSecret | None:
        stmt = select(RuntimeSecret).where(
            RuntimeSecret.client_id.is_(None), RuntimeSecret.provider == provider
        )
        return (await self.session.scalars(stmt)).one_or_none()

    async def upsert_platform(
        self,
        provider: str,
        secrets_enc: bytes,
        updated_by: str,
        *,
        last_test_ok: bool | None = None,
        last_test_at: datetime.datetime | None = None,
    ) -> RuntimeSecret:
        """Satu baris platform per provider. Arbiter `ON CONFLICT` adalah INDEKS parsial (bukan
        constraint), jadi dinyatakan lewat `index_elements` + `index_where`. `updated_at` diisi
        eksplisit karena `onupdate=func.now()` di model tidak jalan untuk `ON CONFLICT DO UPDATE`,
        dan `clock_timestamp()` (bukan `now()`) karena `now()` = awal transaksi: tidak naik di
        antara dua tulis dalam satu transaksi dan lebih tua dari hasil probe yang berdetik-detik.
        `last_test_*` ikut ditimpa: hasil tes lama bukan milik nilai yang baru."""
        insert_stmt = pg_insert(RuntimeSecret).values(
            provider=provider,
            client_id=None,
            secrets_enc=secrets_enc,
            updated_by=updated_by,
            last_test_ok=last_test_ok,
            last_test_at=last_test_at,
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[RuntimeSecret.provider],
            index_where=text("client_id IS NULL"),
            set_={
                "secrets_enc": insert_stmt.excluded.secrets_enc,
                "updated_by": insert_stmt.excluded.updated_by,
                "last_test_ok": insert_stmt.excluded.last_test_ok,
                "last_test_at": insert_stmt.excluded.last_test_at,
                "updated_at": func.clock_timestamp(),
            },
        ).returning(RuntimeSecret)
        result = await self.session.scalars(stmt, execution_options={"populate_existing": True})
        row: RuntimeSecret = result.one()
        await self.session.flush()
        return row

    async def delete_platform(self, provider: str) -> bool:
        result = await self.session.execute(
            delete(RuntimeSecret).where(
                RuntimeSecret.client_id.is_(None), RuntimeSecret.provider == provider
            )
        )
        await self.session.flush()
        return bool(cast(CursorResult[Any], result).rowcount)

    async def record_test(self, provider: str, ok: bool, at: datetime.datetime) -> None:
        """Catat hasil tes terakhir. Tidak membuat baris: provider yang masih dari `.env` tidak
        punya baris override untuk dicatati."""
        await self.session.execute(
            update(RuntimeSecret)
            .where(RuntimeSecret.client_id.is_(None), RuntimeSecret.provider == provider)
            .values(last_test_ok=ok, last_test_at=at)
        )
        await self.session.flush()
