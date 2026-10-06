"""`tools/ops/reconcile_cve_tech.py` -- jalur DB-nya (`load_rows` + `apply_findings`) di Postgres
beneran. Penilainya sendiri diuji di `tests/unit/test_reconcile_cve_tech.py`; di sini yang dikunci:

  1. `delete` membuang baris BESERTA anaknya (reference/affected/poc) dan penanda false positive,
     tapi tidak menyentuh baris CVE yang sama milik client lain.
  2. Baris ber-ticket tidak pernah terhapus; `retag` hanya mengubah kolom `tech`.
  3. `--client` membatasi cakupan; `has_ticket` dan teks affected terbaca benar dari DB."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cti_core.db.models.auth import Client
from cti_core.db.models.cve import (
    CveAffected,
    CveFalsePositive,
    CvePoc,
    CveReference,
    CveTicket,
    CveTracker,
)
from cti_core.db.models.techstack import TechStackEntry
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tools.ops.reconcile_cve_tech import apply_findings, load_rows, plan

ZABBIX = ["Zabbix", "Zabbix"]
ATLASSIAN = ["Atlassian", "Confluence Data Center"]


@pytest.fixture
def session(db_session: Session) -> Iterator[Session]:
    for cid in ("acme", "globex"):
        db_session.add(Client(client_id=cid, name=cid.title()))
    db_session.flush()
    db_session.add_all(
        [
            TechStackEntry(name="mariadb", client_id="acme"),
            TechStackEntry(name="jira", client_id="acme"),
            TechStackEntry(name="confluence", client_id="acme"),
            TechStackEntry(name="mariadb", client_id="globex"),
        ]
    )
    db_session.flush()
    yield db_session


def add(session: Session, cve_id: str, client: str, tech: str, summary: str = "x") -> CveTracker:
    row = CveTracker(cve_id=cve_id, client_id=client, tech=tech, summary=summary)
    row.affected = [CveAffected(affected="Zabbix: < 7.0")]
    row.references = [CveReference(url="https://example.test/ref")]
    session.add(row)
    session.flush()
    return row


def count(session: Session, model: type, **where: object) -> int:
    stmt = select(func.count()).select_from(model)
    for col, value in where.items():
        stmt = stmt.where(getattr(model, col) == value)
    return session.execute(stmt).scalar_one()


def tracked(session: Session) -> dict[tuple[str, str], str]:
    rows = session.execute(select(CveTracker.cve_id, CveTracker.client_id, CveTracker.tech))
    return {(c, cl): t for c, cl, t in rows}


def test_load_rows_reads_affected_text_tickets_and_client_techstack(session: Session) -> None:
    add(session, "CVE-2026-1", "acme", "mariadb")
    add(session, "CVE-2026-2", "acme", "mariadb")
    session.add(CveTicket(cve_id="CVE-2026-2", client_id="acme", ticket_id="CTI-2026-10-001"))
    session.flush()

    rows, techs = load_rows(session, None)

    by_cve = {r.cve_id: r for r in rows}
    assert by_cve["CVE-2026-1"].affected == ("Zabbix: < 7.0",)
    assert (by_cve["CVE-2026-1"].has_ticket, by_cve["CVE-2026-2"].has_ticket) == (False, True)
    assert sorted(techs["acme"]) == ["confluence", "jira", "mariadb"]


def test_load_rows_can_be_limited_to_one_client_and_skips_rows_without_tech(
    session: Session,
) -> None:
    add(session, "CVE-2026-1", "acme", "mariadb")
    add(session, "CVE-2026-1", "globex", "mariadb")
    session.add(CveTracker(cve_id="CVE-2026-9", client_id="acme", tech=None))
    session.flush()

    rows, _ = load_rows(session, "globex")

    assert [(r.cve_id, r.client_id) for r in rows] == [("CVE-2026-1", "globex")]
    assert len(load_rows(session, None)[0]) == 2  # baris tanpa tech tak ikut


def test_apply_deletes_retags_and_protects_exactly_what_the_plan_says(session: Session) -> None:
    doomed = add(session, "CVE-A", "acme", "mariadb")
    doomed.pocs = [CvePoc(url="https://example.test/poc")]
    session.add(CveFalsePositive(cve_id="CVE-A", client_id="acme"))
    add(session, "CVE-A", "globex", "mariadb")  # CVE sama, client lain -> juga salah
    add(session, "CVE-B", "acme", "jira")  # produknya Confluence, client punya confluence
    add(session, "CVE-C", "acme", "mariadb")  # salah, tapi sudah punya ticket
    session.add(CveTicket(cve_id="CVE-C", client_id="acme", ticket_id="CTI-2026-10-001"))
    add(session, "CVE-D", "acme", "mariadb", summary="MariaDB flaw")  # produknya mariadb -> sesuai
    add(session, "CVE-E", "acme", "mariadb")  # MITRE tak terjangkau
    session.flush()
    products = {
        "CVE-A": ZABBIX,
        "CVE-B": ATLASSIAN,
        "CVE-C": ZABBIX,
        "CVE-D": ["MariaDB", "MariaDB Server"],
        "CVE-E": None,
    }

    rows, techs = load_rows(session, "acme")
    result = plan(rows, products, techs)
    done = apply_findings(session, result.findings)
    session.expire_all()

    assert done == {"retag": 1, "delete": 1}
    assert tracked(session) == {
        ("CVE-A", "globex"): "mariadb",  # di luar cakupan `--client acme`
        ("CVE-B", "acme"): "confluence",  # di-retag
        ("CVE-C", "acme"): "mariadb",  # ber-ticket: tidak disentuh
        ("CVE-D", "acme"): "mariadb",
        ("CVE-E", "acme"): "mariadb",  # tak terverifikasi: tidak disentuh
    }
    assert count(session, CveAffected) == 5  # anak CVE-A/acme ikut hilang, sisanya utuh
    assert count(session, CveReference) == 5
    assert count(session, CvePoc) == 0
    assert count(session, CveFalsePositive, cve_id="CVE-A") == 0
    assert count(session, CveTicket) == 1
    assert (result.ok, result.unverified) == (1, 1)


def test_apply_with_no_findings_changes_nothing(session: Session) -> None:
    add(session, "CVE-D", "acme", "mariadb", summary="MariaDB flaw")
    rows, techs = load_rows(session, None)

    done = apply_findings(session, plan(rows, {"CVE-D": ["MariaDB"]}, techs).findings)

    assert done == {"retag": 0, "delete": 0}
    assert count(session, CveTracker) == 1
