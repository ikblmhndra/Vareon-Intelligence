"""`tools/ops/check_orphaned_tickets.py` -- jalur DB-nya (`find_orphans`) di Postgres beneran.

`cve_tickets` berkunci `(cve_id, client_id)` tanpa FK ke `cve_tracker`, jadi tiket bisa ditinggal
yatim oleh `purge-orphaned` versi lama (ROADMAP #20). Yang dikunci: kunci yatim = pasangan
`(cve_id, client_id)` (CVE yang sama di tracker client LAIN tidak menyelamatkan tiketnya),
`--client` membatasi cakupan, dan tool ini hanya membaca."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cti_core.db.models.auth import Client
from cti_core.db.models.cve import CveTicket, CveTracker
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tools.ops.check_orphaned_tickets import find_orphans, render


@pytest.fixture
def session(db_session: Session) -> Iterator[Session]:
    for cid in ("acme", "globex"):
        db_session.add(Client(client_id=cid, name=cid.title()))
    db_session.flush()
    db_session.add(CveTracker(cve_id="CVE-2026-0001", client_id="acme", tech="nginx"))
    db_session.add_all(
        [
            CveTicket(cve_id="CVE-2026-0001", client_id="acme", ticket_id="CTI-2026-10-001"),
            CveTicket(
                cve_id="CVE-2026-0002",
                client_id="acme",
                ticket_id="CTI-2026-10-002",
                remediation_status="Resolved",
                acknowledged_by="analyst",
            ),
            # CVE-nya ada di tracker, tapi hanya milik acme: tiket globex tetap yatim
            CveTicket(cve_id="CVE-2026-0001", client_id="globex", ticket_id="CTI-2026-10-003"),
        ]
    )
    db_session.flush()
    yield db_session


def test_orphans_are_tickets_without_a_tracker_row_for_the_same_client(session: Session) -> None:
    orphans = find_orphans(session, None)

    assert [(o.ticket_id, o.cve_id, o.client_id) for o in orphans] == [
        ("CTI-2026-10-002", "CVE-2026-0002", "acme"),
        ("CTI-2026-10-003", "CVE-2026-0001", "globex"),
    ]
    assert orphans[0].remediation_status == "Resolved"
    assert orphans[0].acknowledged_by == "analyst"


def test_client_filter_limits_the_scope(session: Session) -> None:
    assert [o.ticket_id for o in find_orphans(session, "acme")] == ["CTI-2026-10-002"]
    assert [o.ticket_id for o in find_orphans(session, "globex")] == ["CTI-2026-10-003"]


def test_the_check_only_reads(session: Session) -> None:
    before = session.scalar(select(func.count()).select_from(CveTicket))

    find_orphans(session, None)

    assert session.scalar(select(func.count()).select_from(CveTicket)) == before == 3


def test_render_shows_the_fields_an_analyst_needs_to_decide(session: Session) -> None:
    line = render(find_orphans(session, "acme")[0])

    assert "CTI-2026-10-002" in line and "CVE-2026-0002" in line and "Resolved" in line
    assert "analyst" in line
