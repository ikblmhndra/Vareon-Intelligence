"""Migrasi `7e51efe6d78b` (`daily_recaps.quality`, ROADMAP #21 PR 3): baris yang sudah ada harus
mendapat `{}`, dan penulis lama (yang tidak tahu kolomnya) tetap bisa INSERT.

`test_migrations_match_models` hanya membuktikan SKEMA akhirnya sama dengan model; yang tidak
terlihat di sana adalah DATA dan perilaku default. Pola yang sama dengan `test_recap_migration.py`:
migrasi dijalankan mundur lalu maju DI DALAM satu transaksi yang di-rollback di akhir (DDL Postgres
transaksional), sehingga skema bersama test lain tidak pernah berubah.

Sengaja TIDAK ada test yang mengunci `down_revision` atau "satu head": urutan migrasi antar PR
ditentukan saat merge (migrasi PR lain bisa bersaudara dengan ini), dan fixture `_migrated_schema`
(`alembic upgrade head`) sudah gagal kalau ada lebih dari satu head."""

from __future__ import annotations

import importlib.util
import pathlib
from collections.abc import Callable, Iterator
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cti_core.db.engine import get_sync_engine
from sqlalchemy import text
from sqlalchemy.engine import Connection

_VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"

_INSERT_WITHOUT_QUALITY = (
    "INSERT INTO daily_recaps (date, kind, headline, yesterday, forecast, counts, model, "
    "token_usage) VALUES (:d, 'weekly', :headline, '{}', '{}', '{}', 'm', '{}')"
)


def _load_migration() -> ModuleType:
    path = next(_VERSIONS.glob("7e51efe6d78b_*.py"))
    spec = importlib.util.spec_from_file_location("recap_quality_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(conn: Connection, step: Callable[[], None]) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        step()


@pytest.fixture
def conn(_migrated_schema: None) -> Iterator[Connection]:
    with get_sync_engine().connect() as connection:
        trans = connection.begin()
        yield connection
        trans.rollback()


def test_upgrade_gives_every_existing_row_an_empty_quality(conn: Connection) -> None:
    migration = _load_migration()
    _run(conn, migration.downgrade)  # bentuk sebelum migrasi ini: tanpa kolom `quality`
    conn.execute(text(_INSERT_WITHOUT_QUALITY), {"d": "2026-10-05", "headline": "a"})
    conn.execute(text(_INSERT_WITHOUT_QUALITY), {"d": "2026-10-12", "headline": "b"})

    _run(conn, migration.upgrade)

    rows = conn.execute(text("SELECT date, quality FROM daily_recaps ORDER BY date")).all()
    assert rows == [("2026-10-05", {}), ("2026-10-12", {})]


def test_a_writer_that_does_not_know_the_column_still_inserts_and_gets_the_default(
    conn: Connection,
) -> None:
    """Rollback atau deploy bergulir: kode lama INSERT tanpa `quality`. Kolomnya NOT NULL, jadi
    yang menyelamatkan INSERT itu `server_default`; tanpanya deploy dan rollback jadi 500."""
    conn.execute(text(_INSERT_WITHOUT_QUALITY), {"d": "2026-10-05", "headline": "a"})

    quality = conn.execute(text("SELECT quality FROM daily_recaps")).scalar_one()

    assert quality == {}


def test_downgrade_drops_only_the_column_and_keeps_the_recap(conn: Connection) -> None:
    migration = _load_migration()
    conn.execute(
        text(
            "INSERT INTO daily_recaps (date, kind, headline, yesterday, forecast, counts, model, "
            "token_usage, quality) VALUES ('2026-10-05', 'weekly', 'kept', '{}', '{}', '{}', 'm', "
            "'{}', CAST(:quality AS jsonb))"
        ),
        {"quality": '{"comparison": {}}'},
    )

    _run(conn, migration.downgrade)

    columns = {
        row[0]
        for row in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'daily_recaps'"
            )
        )
    }
    assert "quality" not in columns
    assert conn.execute(text("SELECT headline FROM daily_recaps")).scalar_one() == "kept"
