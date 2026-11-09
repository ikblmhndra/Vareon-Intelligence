"""Task eskalasi ticket CVE (`cve.notify_escalation`, queue `notify`): buat DRAF email Graph ke
lead tim pemilik ticket (spec 2a 4.6, D25). Hanya draf, tidak ada yang terkirim; tanpa Telegram.

Dipicu `PUT /api/cve/{id}/ticket` saat eskalasi menyala (`cti_api.services.cve_escalation`). Task
membaca ulang ticket/tim dari DB (kondisi bisa berubah antara antre dan jalan): eskalasi sudah
dimatikan = lewati; `escalation_notified_at` sudah terisi = lewati (tidak ada draf ganda, termasuk
saat task diulang karena `acks_late`). Kegagalan Graph di-retry (3x, jeda 60 dtk)."""

from __future__ import annotations

from typing import Any

import structlog
from cti_alerts.mailer import create_graph_draft
from cti_api.services.cve_escalation import build_escalation_email, pick_team
from cti_core.db.engine import sync_session
from cti_core.db.models.cve import CveOwnerTeam, CveTicket, CveTracker
from cti_core.runtime_secrets.overlay import effective_settings
from sqlalchemy import func, select, update

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_NOTIFY

log = structlog.get_logger()


@app.task(
    bind=True,
    name="cve.notify_escalation",
    queue=QUEUE_NOTIFY,
    acks_late=True,
    max_retries=3,
    default_retry_delay=60,
)
def notify_escalation(self: Any, client_id: str, cve_id: str, actor: str) -> str:
    with sync_session() as session:
        ticket = session.scalar(
            select(CveTicket).where(CveTicket.cve_id == cve_id, CveTicket.client_id == client_id)
        )
        if ticket is None or not ticket.escalation_required:
            return "skipped_off"
        if ticket.escalation_notified_at is not None:
            return "skipped_done"
        teams = list(
            session.scalars(
                select(CveOwnerTeam).where(
                    CveOwnerTeam.client_id == client_id, CveOwnerTeam.active.is_(True)
                )
            )
        )
        team = pick_team(teams, ticket.owner_team)
        lead = ((team.lead_email if team else None) or "").strip()
        if team is None or not lead:
            log.info("cve_escalation_no_lead", cve_id=cve_id, team=ticket.owner_team)
            return "no_lead"
        graph = effective_settings().graph
        if not all((graph.tenant_id, graph.client_id, graph.client_secret, graph.sender)):
            log.warning("cve_escalation_graph_not_configured", cve_id=cve_id)
            return "graph_not_configured"
        cve = session.scalar(
            select(CveTracker).where(CveTracker.cve_id == cve_id, CveTracker.client_id == client_id)
        )
        subject, html_body = build_escalation_email(
            cve_id=cve_id,
            severity=(cve.cve_severity if cve else None) or "",
            score=cve.cve_score if cve else None,
            kev=bool(cve and cve.cisa_kev),
            exploited=bool(cve and cve.active_exploitation),
            tech=(cve.tech if cve else None) or "",
            ticket_id=ticket.ticket_id,
            team=team.name,
            plan_date=ticket.remediation_date_plan.isoformat()
            if ticket.remediation_date_plan
            else "",
            actor=actor,
        )
        try:
            create_graph_draft(html_body, subject, settings=graph, to=[lead])
        except Exception as e:
            log.warning("cve_escalation_draft_failed", cve_id=cve_id, error=str(e))
            raise self.retry(exc=e) from e
        # `updated_at` dipertahankan: tulisan latar belakang bukan suntingan user.
        session.execute(
            update(CveTicket)
            .where(CveTicket.id == ticket.id)
            .values(escalation_notified_at=func.now(), updated_at=CveTicket.updated_at)
            .execution_options(synchronize_session=False)
        )
    return "drafted"
