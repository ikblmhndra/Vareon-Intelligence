"""`relevance_models` + `RelevanceModelRepo` -- Postgres REAL (testcontainers)."""

from __future__ import annotations

import datetime as dt

import pytest
from cti_core.db.models.relevance import RelevanceModel
from cti_core.db.repositories.relevance import (
    AsyncRelevanceModelRepo,
    RelevanceModelRepo,
    check_status,
)
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

NOW = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.UTC)
COUNTS = {"reject": 10, "best_practice": 5, "threat_news": 20}


@pytest.fixture(autouse=True)
def _clean(db_session: Session) -> None:
    db_session.execute(delete(RelevanceModel))
    db_session.flush()


def _activate(repo: RelevanceModelRepo, artifact: bytes, now: dt.datetime = NOW) -> int:
    return repo.activate(
        artifact=artifact,
        feature_version="fv1",
        n_examples=35,
        class_counts=COUNTS,
        metrics={"agreement": 0.97},
        now=now,
    )


def _row(session: Session, model_id: int) -> RelevanceModel:
    session.expire_all()
    row = session.get(RelevanceModel, model_id)
    assert row is not None
    return row


def test_activate_retires_previous_and_inherits_gate_state(db_session: Session) -> None:
    repo = RelevanceModelRepo(db_session)
    a = _activate(repo, b"A")
    assert _row(db_session, a).gate_state == "shadow"
    assert _row(db_session, a).gate_changed_at is None

    repo.set_gate_state(a, "gate", NOW)
    b = _activate(repo, b"B", NOW + dt.timedelta(hours=1))

    assert _row(db_session, a).status == "retired"
    row_b = _row(db_session, b)
    assert row_b.status == "active"
    assert row_b.gate_state == "gate"
    assert row_b.gate_changed_at == NOW
    active = repo.get_active()
    assert active is not None and active.id == b
    assert active.artifact == b"B"


def test_only_one_active_row(db_session: Session) -> None:
    _activate(RelevanceModelRepo(db_session), b"A")
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(
            text(
                "INSERT INTO relevance_models (status, artifact, feature_version, n_examples,"
                " class_counts, metrics, gate_state) VALUES ('active', '\\x00', 'x', 1,"
                " '{}', '{}', 'shadow')"
            )
        )


def test_purge_keeps_active(db_session: Session) -> None:
    repo = RelevanceModelRepo(db_session)
    old = NOW - dt.timedelta(days=100)
    _activate(repo, b"A", old)
    rejected = repo.add_rejected(
        feature_version="fv1", n_examples=3, class_counts=COUNTS, metrics={}, reason="too few"
    )
    active = _activate(repo, b"B", old)  # retires A
    db_session.execute(
        text("UPDATE relevance_models SET created_at = :t"), {"t": NOW - dt.timedelta(days=100)}
    )

    deleted = repo.purge(NOW - dt.timedelta(days=90))

    assert deleted == 2
    assert repo.get_active() is not None
    assert repo.get_active().id == active  # type: ignore[union-attr]
    db_session.expire_all()
    assert db_session.get(RelevanceModel, rejected) is None


def test_invalid_status_rejected(db_session: Session) -> None:
    repo = RelevanceModelRepo(db_session)
    with pytest.raises(ValueError):
        repo.set_gate_state(1, "bogus", NOW)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        check_status("bogus")
    check_status("rejected")


async def test_async_get_active(async_db_session: AsyncSession) -> None:
    repo = AsyncRelevanceModelRepo(async_db_session)
    active = await repo.get_active()
    assert active is None or active.status == "active"
