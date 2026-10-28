"""Migrasi 0.8.11 (`a9e4c7b1d3f6`): `iocs*` -> `indicators*` + view kompatibilitas -- Postgres REAL.

Skema test sudah di head, jadi test mundur dulu ke bentuk lama lewat `downgrade()` migrasi ini
(transaksi sesi, di-rollback di akhir), menyemai data lama, lalu menjalankan `upgrade()`."""

from __future__ import annotations

import importlib.util
import pathlib
from collections.abc import Iterator
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

_VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load_migration() -> ModuleType:
    path = next(_VERSIONS.glob("a9e4c7b1d3f6_*.py"))
    spec = importlib.util.spec_from_file_location("indicators_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def _run(session: Session, fn: str) -> None:
    ctx = MigrationContext.configure(session.connection())
    with Operations.context(ctx):
        getattr(migration, fn)()


def _relkind(session: Session, name: str) -> str | None:
    return session.execute(
        text(
            "SELECT relkind FROM pg_class"
            " WHERE relname = :n AND relnamespace = 'public'::regnamespace"
        ),
        {"n": name},
    ).scalar_one_or_none()


@pytest.fixture
def old_schema(db_session: Session) -> Iterator[Session]:
    """Skema pra-0.8.11 dengan 2 `iocs` dan satu baris di tiap tabel anak."""
    _run(db_session, "downgrade")
    ids = [
        db_session.execute(
            text(
                "INSERT INTO iocs (type, value, seen_count, tp_count, fp_count, auto_suppressed,"
                " enrichment, confidence_score) VALUES ('domain', :v, 1, 0, 0, false, '{}', 50)"
                " RETURNING id"
            ),
            {"v": v},
        ).scalar_one()
        for v in ("a.example", "b.example")
    ]
    first = ids[0]
    db_session.execute(
        text("INSERT INTO ioc_sources (ioc_id, url, source_name) VALUES (:i, 'u', 's')"),
        {"i": first},
    )
    db_session.execute(text("INSERT INTO ioc_tags (ioc_id, tag) VALUES (:i, 't')"), {"i": first})
    db_session.execute(
        text("INSERT INTO ioc_threat_actors (ioc_id, threat_actor) VALUES (:i, 'apt')"),
        {"i": first},
    )
    db_session.execute(
        text("INSERT INTO ioc_feedback (ioc_id, verdict, submitted_by) VALUES (:i, 'tp', 'x')"),
        {"i": first},
    )
    db_session.info["ids"] = ids
    yield db_session


def test_upgrade_keeps_rows_and_ids(old_schema: Session) -> None:
    ids = old_schema.info["ids"]
    _run(old_schema, "upgrade")

    rows = old_schema.execute(text("SELECT id, value FROM indicators ORDER BY id")).all()
    assert rows == [(ids[0], "a.example"), (ids[1], "b.example")]
    for table in (
        "indicator_sources",
        "indicator_tags",
        "indicator_threat_actors",
        "indicator_feedback",
    ):
        assert old_schema.execute(text(f"SELECT indicator_id FROM {table}")).scalars().all() == [
            ids[0]
        ]
    assert _relkind(old_schema, "iocs") == "v"
    assert _relkind(old_schema, "indicators") == "r"


def test_compat_views_readable(old_schema: Session) -> None:
    ids = old_schema.info["ids"]
    _run(old_schema, "upgrade")

    assert old_schema.execute(text("SELECT count(*) FROM iocs")).scalar_one() == 2
    for table in ("ioc_sources", "ioc_tags", "ioc_threat_actors", "ioc_feedback"):
        assert old_schema.execute(text(f"SELECT ioc_id FROM {table}")).scalars().all() == [ids[0]]


def test_insert_after_rename_uses_sequence(old_schema: Session) -> None:
    ids = old_schema.info["ids"]
    _run(old_schema, "upgrade")

    new_id = old_schema.execute(
        text(
            "INSERT INTO indicators (type, value, seen_count, tp_count, fp_count, auto_suppressed,"
            " enrichment, confidence_score) VALUES ('ip', '1.2.3.4', 1, 0, 0, false, '{}', 50)"
            " RETURNING id"
        )
    ).scalar_one()
    assert new_id == max(ids) + 1


def test_downgrade_restores_iocs(old_schema: Session) -> None:
    ids = old_schema.info["ids"]
    _run(old_schema, "upgrade")
    _run(old_schema, "downgrade")

    assert _relkind(old_schema, "iocs") == "r"
    assert _relkind(old_schema, "indicators") is None
    assert old_schema.execute(text("SELECT id FROM iocs ORDER BY id")).scalars().all() == ids
    for table in ("ioc_sources", "ioc_tags", "ioc_threat_actors", "ioc_feedback"):
        assert old_schema.execute(text(f"SELECT ioc_id FROM {table}")).scalars().all() == [ids[0]]


def test_new_columns_backfill(old_schema: Session) -> None:
    _run(old_schema, "upgrade")

    rows = old_schema.execute(
        text(
            "SELECT valid_from = first_seen_at, valid_until IS NULL, tlp, pap, revoked_at IS NULL"
            " FROM indicators"
        )
    ).all()
    assert rows == [(True, True, "clear", "clear", True)] * 2
    # view kompatibilitas dibuat sesudah kolom baru, jadi ikut membawanya
    assert old_schema.execute(text("SELECT tlp FROM iocs LIMIT 1")).scalar_one() == "clear"

    with pytest.raises(IntegrityError), old_schema.begin_nested():
        old_schema.execute(text("UPDATE indicators SET tlp = 'purple'"))
    with pytest.raises(IntegrityError), old_schema.begin_nested():
        old_schema.execute(text("UPDATE indicators SET pap = 'purple'"))

    _run(old_schema, "downgrade")
    cols = (
        old_schema.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'iocs'")
        )
        .scalars()
        .all()
    )
    assert "valid_from" not in cols
