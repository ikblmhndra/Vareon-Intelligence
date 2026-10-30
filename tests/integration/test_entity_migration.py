"""Migrasi `entity_model` (P7c-1) pada Postgres NYATA: trigger tipe alias dan downgrade bersih."""

from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

_VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load_migration() -> ModuleType:
    path = next(_VERSIONS.glob("*_entity_model.py"))
    spec = importlib.util.spec_from_file_location("entity_model_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def _run(session: Session, fn: str) -> None:
    ctx = MigrationContext.configure(session.connection())
    with Operations.context(ctx):
        getattr(migration, fn)()


def _entity(session: Session, type_: str, name: str) -> int:
    return session.execute(
        text(
            "INSERT INTO entities (type, stix_id, name, source) VALUES (:t, :s, :n, 'analyst')"
            " RETURNING id"
        ),
        {"t": type_, "s": f"{type_}--{name}", "n": name},
    ).scalar_one()


def _alias(session: Session, entity_id: int, norm: str) -> None:
    # entity_type sengaja salah: trigger harus menimpanya.
    session.execute(
        text(
            "INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)"
            " VALUES (:e, 'bogus', :a, :a, 'analyst')"
        ),
        {"e": entity_id, "a": norm},
    )


def test_trigger_sets_alias_entity_type(db_session: Session) -> None:
    eid = _entity(db_session, "malware", "Emotet")
    _alias(db_session, eid, "emotet")
    got = db_session.execute(text("SELECT entity_type FROM entity_aliases")).scalar_one()
    assert got == "malware"


def test_alias_unique_per_type_not_across_types(db_session: Session) -> None:
    actor = _entity(db_session, "intrusion-set", "Lazarus")
    other = _entity(db_session, "intrusion-set", "Lazarus Group")
    tool = _entity(db_session, "tool", "Lazarus")
    _alias(db_session, actor, "lazarus")
    _alias(db_session, tool, "lazarus")  # beda tipe: boleh
    with pytest.raises(IntegrityError), db_session.begin_nested():
        _alias(db_session, other, "lazarus")  # tipe sama: ditolak walau SQL mentah


def test_downgrade_drops_everything(db_session: Session) -> None:
    _run(db_session, "downgrade")
    left = db_session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables WHERE table_name IN"
            " ('entities','entity_aliases','relationships','entity_mentions','entity_watches',"
            "'entity_profiles','reference_snapshots')"
        )
    ).scalar_one()
    assert left == 0
    assert not db_session.execute(
        text("SELECT 1 FROM pg_proc WHERE proname = 'entity_aliases_sync_type'")
    ).first()
    _run(db_session, "upgrade")  # bolak-balik harus mulus
