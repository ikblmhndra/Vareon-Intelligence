"""Migrasi `machine_api` (P7b): `api_tokens`, jam feed `feed_changed_at`, `stix_id`, trigger --
Postgres REAL.

Di dalam satu transaksi test `now()` konstan, jadi tiap test bump lebih dulu memundurkan
`feed_changed_at` ke 2020-01-01 lewat UPDATE polos (tak ada kolom terpantau yang berubah, jadi
trigger membiarkan nilai yang di-assign), baru mengubah field dan menegaskan `= now()`."""

from __future__ import annotations

import importlib.util
import pathlib
from collections.abc import Iterator
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cti_core.config import IndicatorSettings
from cti_core.db.repositories.indicator import AsyncIndicatorRepo, IndicatorRepo
from cti_core.indicator.stix_id import indicator_uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"
_OLD = "2020-01-01T00:00:00Z"


def _load_migration() -> ModuleType:
    path = next(_VERSIONS.glob("*_machine_api.py"))
    spec = importlib.util.spec_from_file_location("machine_api_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def _run(session: Session, fn: str) -> None:
    ctx = MigrationContext.configure(session.connection())
    with Operations.context(ctx):
        getattr(migration, fn)()


_BASE = "seen_count, tp_count, fp_count, auto_suppressed, enrichment, confidence_score"
_BASE_VALUES = "1, 0, 0, false, '{}', 50"


def _insert(session: Session, value: str, type: str = "domain") -> int:
    return session.execute(
        text(
            f"INSERT INTO indicators (type, value, {_BASE}) VALUES (:t, :v, {_BASE_VALUES})"
            " RETURNING id"
        ),
        {"t": type, "v": value},
    ).scalar_one()


def _age(session: Session, ind_id: int) -> None:
    session.execute(
        text("UPDATE indicators SET feed_changed_at = :t WHERE id = :i"), {"t": _OLD, "i": ind_id}
    )


def _bumped(session: Session, ind_id: int) -> bool:
    return session.execute(
        text("SELECT feed_changed_at = now() FROM indicators WHERE id = :i"), {"i": ind_id}
    ).scalar_one()


@pytest.fixture
def ind(db_session: Session) -> Iterator[tuple[Session, int]]:
    ind_id = _insert(db_session, "trigger.example")
    _age(db_session, ind_id)
    assert not _bumped(db_session, ind_id)
    yield db_session, ind_id


def test_upgrade_backfills_feed_changed_at_and_stix_id(db_session: Session) -> None:
    _run(db_session, "downgrade")
    db_session.execute(
        text(
            f"INSERT INTO indicators (type, value, created_at, revoked_at, {_BASE}) VALUES"
            f" ('ip', '1.2.3.4', '2026-01-01Z', NULL, {_BASE_VALUES}),"
            f" ('domain', 'Evil.Example', '2026-01-01Z', '2026-02-01Z', {_BASE_VALUES})"
        )
    )
    _run(db_session, "upgrade")

    rows = db_session.execute(
        text(
            "SELECT type, value, stix_id,"
            " feed_changed_at = greatest(created_at, coalesce(revoked_at, created_at))"
            " FROM indicators ORDER BY id"
        )
    ).all()
    assert len(rows) == 2
    for t, v, stix_id, ok in rows:
        assert ok
        assert stix_id == indicator_uuid(t, v)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("revoked_at", "now()"),
        ("auto_suppressed", "true"),
        ("tlp", "'amber'"),
        ("pap", "'amber'"),
        ("valid_until", "now() + interval '1 day'"),
        ("seen_count", "99"),
        ("last_seen_at", "now() + interval '1 hour'"),
    ],
)
def test_trigger_bumps_on_feed_fields(ind: tuple[Session, int], column: str, value: str) -> None:
    session, ind_id = ind
    session.execute(text(f"UPDATE indicators SET {column} = {value} WHERE id = :i"), {"i": ind_id})
    assert _bumped(session, ind_id)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("confidence_score", "7"),
        ("actionability_score", "7"),
        ("enrichment", "'{\"a\": 1}'::jsonb"),
        ("updated_at", "now()"),
    ],
)
def test_trigger_ignores_confidence_and_enrichment(
    ind: tuple[Session, int], column: str, value: str
) -> None:
    session, ind_id = ind
    session.execute(text(f"UPDATE indicators SET {column} = {value} WHERE id = :i"), {"i": ind_id})
    assert not _bumped(session, ind_id)


def test_tag_insert_delete_bumps_parent(ind: tuple[Session, int]) -> None:
    session, ind_id = ind
    session.execute(
        text("INSERT INTO indicator_tags (indicator_id, tag) VALUES (:i, 'phish')"), {"i": ind_id}
    )
    assert _bumped(session, ind_id)
    _age(session, ind_id)
    session.execute(text("DELETE FROM indicator_tags WHERE indicator_id = :i"), {"i": ind_id})
    assert _bumped(session, ind_id)


def test_reconcile_raw_update_bumps(db_session: Session) -> None:
    ind_id = _insert(db_session, "1.2.3.5", type="ip")
    _age(db_session, ind_id)
    IndicatorRepo(db_session).reconcile_validity(IndicatorSettings())
    assert _bumped(db_session, ind_id)


def test_reconcile_fills_null_stix_id(db_session: Session) -> None:
    ind_id = _insert(db_session, "Null-Stix.Example")
    assert (
        db_session.execute(
            text("SELECT stix_id FROM indicators WHERE id = :i"), {"i": ind_id}
        ).scalar_one()
        is None
    )
    IndicatorRepo(db_session).reconcile_validity(IndicatorSettings())
    got = db_session.execute(
        text("SELECT stix_id FROM indicators WHERE id = :i"), {"i": ind_id}
    ).scalar_one()
    assert got == indicator_uuid("domain", "Null-Stix.Example")


def test_upsert_sets_stix_id(db_session: Session) -> None:
    ind = IndicatorRepo(db_session).upsert(
        type="ip", value="198.51.100.9", source_url="https://s/1", source_name="s"
    )
    assert ind.stix_id == indicator_uuid("ip", "198.51.100.9")


async def test_async_upsert_sets_stix_id(async_db_session: AsyncSession) -> None:
    ind = await AsyncIndicatorRepo(async_db_session).upsert(
        type="domain", value="Async.Example", source_url="https://s/1", source_name="s"
    )
    assert ind.stix_id == indicator_uuid("domain", "Async.Example")


def test_insert_through_compat_view_gets_defaults(db_session: Session) -> None:
    ind_id = db_session.execute(
        text(
            "INSERT INTO iocs (type, value, seen_count, tp_count, fp_count, auto_suppressed,"
            " enrichment, confidence_score) VALUES ('ip', '203.0.113.7', 1, 0, 0, false, '{}', 50)"
            " RETURNING id"
        )
    ).scalar_one()
    assert _bumped(db_session, ind_id)
    stix_id = db_session.execute(
        text("SELECT stix_id FROM indicators WHERE id = :i"), {"i": ind_id}
    ).scalar_one()
    assert stix_id is None


def test_downgrade_removes_everything(db_session: Session) -> None:
    _run(db_session, "downgrade")
    assert db_session.execute(text("SELECT to_regclass('api_tokens')")).scalar_one() is None
    cols = (
        db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'indicators'"
            )
        )
        .scalars()
        .all()
    )
    assert "feed_changed_at" not in cols and "stix_id" not in cols
    assert (
        db_session.execute(
            text(
                "SELECT count(*) FROM pg_indexes"
                " WHERE indexname = 'ix_indicators_feed_changed_at_id'"
            )
        ).scalar_one()
        == 0
    )
    assert (
        db_session.execute(
            text(
                "SELECT count(*) FROM pg_proc WHERE proname IN"
                " ('indicators_feed_bump', 'indicator_tags_feed_bump')"
            )
        ).scalar_one()
        == 0
    )
    assert (
        db_session.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgname IN"
                " ('trg_indicators_feed_bump', 'trg_indicator_tags_feed_bump')"
            )
        ).scalar_one()
        == 0
    )


def test_case_variants_get_distinct_stix_ids(db_session: Session) -> None:
    repo = IndicatorRepo(db_session)
    kw = {"source_url": "https://s/1", "source_name": "s"}
    a = repo.upsert(type="url", value="http://a/B", **kw)
    b = repo.upsert(type="url", value="http://a/b", **kw)
    assert a.stix_id != b.stix_id


def test_backfill_case_variants_distinct(db_session: Session) -> None:
    _run(db_session, "downgrade")
    db_session.execute(
        text(
            f"INSERT INTO indicators (type, value, {_BASE}) VALUES"
            f" ('url', 'http://a/B', {_BASE_VALUES}), ('url', 'http://a/b', {_BASE_VALUES})"
        )
    )
    _run(db_session, "upgrade")
    ids = db_session.execute(text("SELECT stix_id FROM indicators")).scalars().all()
    assert len(ids) == 2 and len(set(ids)) == 2


def test_upsert_fills_null_stix_id_on_existing(db_session: Session) -> None:
    ind_id = _insert(db_session, "legacy.example")
    ind = IndicatorRepo(db_session).upsert(
        type="domain", value="legacy.example", source_url="https://s/1", source_name="s"
    )
    assert ind.id == ind_id
    assert ind.stix_id == indicator_uuid("domain", "legacy.example")
