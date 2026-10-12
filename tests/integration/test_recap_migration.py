"""Migrasi `f6c3a9d2b8e1` (`daily_recaps.kind` + `period_start`/`period_end`, ROADMAP #21 PR 2):
baris lama harus jadi `daily` dengan periode = `date`, dan unik berpindah dari `date` ke
`(kind, date)`.

`test_migrations_match_models` hanya membuktikan SKEMA akhirnya sama dengan model; yang tidak
terlihat di sana adalah DATA: backfill baris yang sudah ada. Untuk mengujinya, migrasi dijalankan
mundur lalu maju DI DALAM satu transaksi yang di-rollback di akhir (DDL Postgres transaksional),
sehingga skema bersama test lain tidak pernah berubah, juga kalau test ini gagal di tengah."""

from __future__ import annotations

import datetime
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
from sqlalchemy.exc import IntegrityError

_VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"

_INSERT = (
    "INSERT INTO daily_recaps (date, kind, headline, yesterday, forecast, counts, model, "
    "token_usage) VALUES (:d, :kind, 'x', '{}', '{}', '{}', 'm', '{}')"
)
_INSERT_LEGACY = (
    "INSERT INTO daily_recaps (date, headline, yesterday, forecast, counts, model, token_usage) "
    "VALUES (:d, 'legacy', '{}', '{}', '{}', 'm', '{}')"
)


def _load_migration() -> ModuleType:
    path = next(_VERSIONS.glob("f6c3a9d2b8e1_*.py"))
    spec = importlib.util.spec_from_file_location("recap_kind_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(conn: Connection, step: Callable[[], None]) -> None:
    """`step` (`upgrade`/`downgrade` migrasi) dengan `op` terikat ke koneksi ini."""
    with Operations.context(MigrationContext.configure(conn)):
        step()


@pytest.fixture
def conn(_migrated_schema: None) -> Iterator[Connection]:
    """Koneksi dalam transaksi; rollback di akhir mengembalikan skema head apa pun yang dilakukan
    test (termasuk DDL)."""
    with get_sync_engine().connect() as connection:
        trans = connection.begin()
        yield connection
        trans.rollback()


def test_upgrade_backfills_existing_rows_as_daily_with_period_equal_to_date(
    conn: Connection,
) -> None:
    migration = _load_migration()
    _run(conn, migration.downgrade)  # kembali ke bentuk sebelum migrasi ini
    conn.execute(text(_INSERT_LEGACY), {"d": "2026-09-18"})
    conn.execute(text(_INSERT_LEGACY), {"d": "2026-10-05"})

    _run(conn, migration.upgrade)

    rows = conn.execute(
        text("SELECT date, kind, period_start, period_end FROM daily_recaps ORDER BY date")
    ).all()
    assert rows == [
        ("2026-09-18", "daily", datetime.date(2026, 9, 18), datetime.date(2026, 9, 18)),
        ("2026-10-05", "daily", datetime.date(2026, 10, 5), datetime.date(2026, 10, 5)),
    ]


def test_upgrade_moves_uniqueness_from_date_to_kind_and_date(conn: Connection) -> None:
    migration = _load_migration()
    _run(conn, migration.downgrade)
    # Skema lama: dua baris dengan `date` sama ditolak.
    conn.execute(text(_INSERT_LEGACY), {"d": "2026-10-05"})
    with pytest.raises(IntegrityError, match="uq_daily_recap_date"), conn.begin_nested():
        conn.execute(text(_INSERT_LEGACY), {"d": "2026-10-05"})

    _run(conn, migration.upgrade)

    # Skema baru: mingguan dan harian boleh berbagi Senin, dua mingguan yang sama tidak.
    conn.execute(text(_INSERT), {"d": "2026-10-05", "kind": "weekly"})
    with pytest.raises(IntegrityError, match="uq_daily_recap_kind_date"), conn.begin_nested():
        conn.execute(text(_INSERT), {"d": "2026-10-05", "kind": "weekly"})


def test_downgrade_works_with_one_row_per_date_and_is_refused_when_two_kinds_share_one(
    conn: Connection,
) -> None:
    """Yang dijanjikan docstring migrasinya: constraint lama menolak downgrade kalau ada dua
    baris di `date` yang sama, dan downgrade mulus kalau tidak ada."""
    migration = _load_migration()
    conn.execute(text(_INSERT), {"d": "2026-10-05", "kind": "daily"})
    with conn.begin_nested():
        _run(conn, migration.downgrade)  # satu baris per `date`: aman
    _run(conn, migration.upgrade)
    conn.execute(text(_INSERT), {"d": "2026-10-05", "kind": "weekly"})

    with pytest.raises(IntegrityError, match="uq_daily_recap_date"), conn.begin_nested():
        _run(conn, migration.downgrade)
