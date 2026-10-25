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
