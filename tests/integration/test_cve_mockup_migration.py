"""Migrasi `b7d41e9a2c63`: backfill `cve_tickets.updated_by` dan seed `cve_owner_teams` dari
`owner_team` bebas yang sudah ada -- Postgres REAL."""

from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType

from sqlalchemy import text
from sqlalchemy.orm import Session

_VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load_migration() -> ModuleType:
    path = next(_VERSIONS.glob("b7d41e9a2c63_*.py"))
    spec = importlib.util.spec_from_file_location("cve_tracker_mockup_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mig = _load_migration()


def _client(session: Session, client_id: str) -> None:
    session.execute(
        text(
            "INSERT INTO clients (client_id, name, created_at, updated_at)"
            " VALUES (:c, :c, now(), now()) ON CONFLICT DO NOTHING"
        ),
        {"c": client_id},
    )


def _ticket(
    session: Session,
    n: int,
    client_id: str,
    *,
    owner_team: str | None = None,
    acknowledged_by: str | None = None,
) -> None:
    session.execute(
        text(
            "INSERT INTO cve_tickets (cve_id, client_id, ticket_id, owner_team, acknowledged_by,"
            " escalation_required, created_at, updated_at)"
            " VALUES (:cve, :c, :tid, :team, :ack, false, now(), now())"
        ),
        {
            "cve": f"CVE-2026-{n:04d}",
            "c": client_id,
            "tid": f"CTI-MIG-{n:04d}",
            "team": owner_team,
            "ack": acknowledged_by,
        },
    )


def test_backfill_updated_by_copies_acknowledged_by(db_session: Session) -> None:
    _client(db_session, "default")
    _ticket(db_session, 1, "default", acknowledged_by="alice")
    _ticket(db_session, 2, "default")

    db_session.execute(text(mig.BACKFILL_UPDATED_BY_SQL))

    rows = dict(
        db_session.execute(
            text("SELECT cve_id, updated_by FROM cve_tickets WHERE ticket_id LIKE 'CTI-MIG-%'")
        ).all()
    )
    assert rows == {"CVE-2026-0001": "alice", "CVE-2026-0002": None}


def test_backfill_owner_teams_distinct_trimmed_per_client(db_session: Session) -> None:
    _client(db_session, "default")
    _client(db_session, "acme")
    for n, team in enumerate(["SOC", " SOC ", "soc", "", None], start=1):
        _ticket(db_session, n, "default", owner_team=team)
    _ticket(db_session, 10, "acme", owner_team="SOC")

    db_session.execute(text(mig.BACKFILL_OWNER_TEAMS_SQL))
    db_session.execute(text(mig.BACKFILL_OWNER_TEAMS_SQL))  # idempoten

    def names(client_id: str) -> set[str]:
        return set(
            db_session.execute(
                text("SELECT name FROM cve_owner_teams WHERE client_id = :c"), {"c": client_id}
            ).scalars()
        )

    assert names("default") == {"SOC", "soc"}
    assert names("acme") == {"SOC"}
    actives = db_session.execute(text("SELECT active FROM cve_owner_teams")).scalars().all()
    assert actives and all(actives)
