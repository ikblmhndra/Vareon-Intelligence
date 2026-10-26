"""Stage tier 1 terhadap Postgres REAL (testcontainers), P4 Task 6."""

from __future__ import annotations

import time

import pytest
from cti_core.db.models.threat_reference import ThreatActorGroup
from cti_enrich.stages import tier1
from cti_enrich.stages.tier1 import get_dictionary, run_tier1
from sqlalchemy import event
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    tier1._dictionary_cache = None
    tier1._dictionary_cache_ts = 0.0
    tier1._catalog_cache = None
    tier1._catalog_loaded = False


def test_run_tier1_without_attack_data(db_session: Session) -> None:
    db_session.add(ThreatActorGroup(name="kimsuky", source="manual"))
    db_session.flush()

    result = run_tier1(
        session=db_session,
        title="North Korean APT Kimsuky targets researchers",
        text="North Korean APT Kimsuky used spearphishing, tracked as T1059.",
        victim_name=None,
    )

    assert result.actors == ["kimsuky"]
    assert result.techniques == []


def test_dictionary_cache_ttl(db_session: Session) -> None:
    db_session.add(ThreatActorGroup(name="kimsuky", source="manual"))
    db_session.flush()
    statements: list[str] = []

    def count(conn, cursor, statement, *args):  # type: ignore[no-untyped-def]
        statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", count)
    try:
        first = get_dictionary(db_session)
        after_first = len(statements)
        second = get_dictionary(db_session)
    finally:
        event.remove(bind, "before_cursor_execute", count)

    assert after_first > 0
    assert len(statements) == after_first
    assert second is first
    assert time.monotonic() - tier1._dictionary_cache_ts < 3600


def test_dictionary_load_failure_keeps_session_usable(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select, text

    def broken(session: Session) -> object:
        session.execute(text("SELECT * FROM tabel_yang_tidak_ada"))
        raise AssertionError("tidak tercapai")

    monkeypatch.setattr(tier1, "load_entity_sources", broken)

    dictionary = get_dictionary(db_session)

    assert dict(dictionary.entries) == {}
    assert db_session.execute(select(ThreatActorGroup.id)).all() is not None
    # gagal tanpa kamus lama: dicoba lagi sesudah _RETRY_AFTER, bukan di-cache satu jam
    monkeypatch.undo()
    tier1._dictionary_cache_ts = time.monotonic() - tier1._RETRY_AFTER - 1
    db_session.add(ThreatActorGroup(name="kimsuky", source="manual"))
    db_session.flush()
    assert "kimsuky" in get_dictionary(db_session).entries


def test_catalog_cached_within_ttl(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = tier1.load_catalog

    def counting(session: Session) -> object:
        calls.append(1)
        return real(session)

    monkeypatch.setattr(tier1, "load_catalog", counting)
    tier1._catalog_cache = None
    tier1._catalog_loaded = False
    for _ in range(2):
        run_tier1(session=db_session, title="t", text="b", victim_name=None)
    assert len(calls) == 1


def test_catalog_failure_keeps_session_usable_and_entities(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select, text

    db_session.add(ThreatActorGroup(name="kimsuky", source="manual"))
    db_session.flush()

    def broken(session: Session) -> object:
        session.execute(text("SELECT * FROM tabel_yang_tidak_ada"))
        raise AssertionError("tidak tercapai")

    monkeypatch.setattr(tier1, "load_catalog", broken)
    tier1._catalog_cache = None
    tier1._catalog_loaded = False

    result = run_tier1(
        session=db_session,
        title="North Korean APT Kimsuky targets researchers",
        text="Kimsuky group operators used spearphishing.",
        victim_name=None,
    )

    assert result.actors == ["kimsuky"]
    assert db_session.execute(select(ThreatActorGroup.id)).all() is not None
