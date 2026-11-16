"""Task `cve.notify_escalation`: draf ke lead, penanda `escalation_notified_at`, aturan lewati.
Butuh DB sungguhan (task membaca ticket/tim), jadi di tests/integration."""

from __future__ import annotations

import contextlib
import datetime
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from cti_core.config import GraphSettings
from cti_core.db.models.cve import CveOwnerTeam, CveTicket, CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo  # noqa: F401
from sqlalchemy import select, text
from sqlalchemy.orm import Session

CVE = "CVE-2026-7101"
FULL = GraphSettings(tenant_id="t", client_id="c", client_secret="s", sender="cti@example.com")


@pytest.fixture
def cve_notify(_configured_settings: None) -> Any:
    """Import malas: `cti_worker.celery_app` membaca Settings saat import, padahal env test baru
    dipasang fixture `_configured_settings`."""
    from cti_worker.tasks import cve_notify as module

    return module


@pytest.fixture
def session(db_session: Session, cve_notify: Any, monkeypatch: pytest.MonkeyPatch) -> Session:
    @contextlib.contextmanager
    def _shared() -> Iterator[Session]:
        yield db_session
        db_session.flush()

    monkeypatch.setattr(cve_notify, "sync_session", _shared)
    db_session.execute(
        text(
            "INSERT INTO clients (client_id, name) VALUES ('default', 'Default') "
            "ON CONFLICT DO NOTHING"
        )
    )
    db_session.add(CveTracker(cve_id=CVE, client_id="default", tech="nginx", cve_severity="HIGH"))
    db_session.add(
        CveOwnerTeam(client_id="default", name="SOC", lead_email="lead@example.com", active=True)
    )
    db_session.flush()
    return db_session


@pytest.fixture
def drafts(cve_notify: Any, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(html: str, subject: str, **kw: Any) -> str:
        calls.append({"subject": subject, "html": html, **kw})
        return "msg-1"

    monkeypatch.setattr(cve_notify, "create_graph_draft", fake)
    monkeypatch.setattr(cve_notify, "effective_settings", lambda: SimpleNamespace(graph=FULL))
    return calls


def _ticket(session: Session, *, required: bool = True, notified: bool = False) -> CveTicket:
    t = CveTicket(
        cve_id=CVE,
        client_id="default",
        ticket_id="CTI-2026-11-777",
        updated_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1),
        owner_team="SOC",
        escalation_required=required,
        escalation_notified_at=datetime.datetime.now(datetime.UTC) if notified else None,
    )
    session.add(t)
    session.flush()
    session.refresh(t)
    return t


def _run(cve_notify: Any) -> str:
    return cve_notify.notify_escalation.run("default", CVE, "tester")


def test_task_drafts_to_lead_and_sets_notified_at(
    session: Session, drafts: list[dict[str, Any]], cve_notify: Any
) -> None:
    t = _ticket(session)
    before = t.updated_at
    assert _run(cve_notify) == "drafted"
    assert drafts[0]["to"] == ["lead@example.com"]
    session.expire_all()
    t = session.execute(select(CveTicket).where(CveTicket.cve_id == CVE)).scalar_one()
    assert t.escalation_notified_at is not None
    assert t.updated_at == before


def test_task_skips_when_already_notified(
    session: Session, drafts: list[dict[str, Any]], cve_notify: Any
) -> None:
    _ticket(session, notified=True)
    assert _run(cve_notify) == "skipped_done"
    assert drafts == []


def test_task_skips_when_escalation_off(
    session: Session, drafts: list[dict[str, Any]], cve_notify: Any
) -> None:
    _ticket(session, required=False)
    assert _run(cve_notify) == "skipped_off"
    assert drafts == []


def test_task_graph_not_configured(
    session: Session,
    drafts: list[dict[str, Any]],
    cve_notify: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cve_notify,
        "effective_settings",
        lambda: SimpleNamespace(graph=GraphSettings(client_id="c", client_secret="s", sender="x")),
    )
    _ticket(session)
    assert _run(cve_notify) == "graph_not_configured"
    assert drafts == []
