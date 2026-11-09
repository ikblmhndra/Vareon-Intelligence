"""Eskalasi ticket CVE (spec 2a 4.6, D25): saat `escalation_required` menyala, SATU draf email
Graph dibuat untuk lead tim pemilik. Hanya draf (analis mengirim manual dari Outlook), tanpa
Telegram, tanpa setting baru.

API hanya MENGIRIM tugas lewat nama (`cti_core.celery_client`, tanpa import worker) dan hanya
SESUDAH commit; tugasnya (`cti_worker.tasks.cve_notify`) yang membuat draf. Best effort: broker
mati tidak pernah menggagalkan simpan ticket (hasilnya `failed`).

Penanda "sudah dikirim" = `CveTicket.escalation_notified_at`; router mengosongkannya saat eskalasi
dimatikan, jadi menyalakan lagi sesudahnya membuat draf baru. Menyimpan ulang ticket yang sudah
tereskalasi tidak membuat draf kedua (`is_newly_escalated`)."""

from __future__ import annotations

import html
from collections.abc import Iterable
from typing import Literal

import structlog
from cti_core.celery_client import get_celery_client
from cti_core.db.models.cve import CveOwnerTeam

log = structlog.get_logger()

TASK_NAME = "cve.notify_escalation"
QUEUE = "notify"  # = `cti_worker.queues.QUEUE_NOTIFY` (API tidak boleh import worker)

EscalationResult = Literal["queued", "not_needed", "no_lead", "failed"]


def is_newly_escalated(old_required: bool | None, new_required: bool) -> bool:
    """`old_required` None = ticket belum ada. Hanya transisi mati -> nyala yang dihitung."""
    return new_required and not old_required


def pick_team(teams: Iterable[CveOwnerTeam], owner_team: str | None) -> CveOwnerTeam | None:
    """Tim untuk `owner_team` ticket: nama persis (setelah trim, huruf besar/kecil dibedakan, sama
    dengan aturan `AsyncCveOwnerTeamRepo`); bila tidak ada, satu-satunya kecocokan
    case-insensitive; selain itu None (dua kandidat = ambigu, jangan menebak lead)."""
    name = (owner_team or "").strip()
    if not name:
        return None
    candidates = list(teams)
    for team in candidates:
        if team.name == name:
            return team
    loose = [t for t in candidates if t.name.lower() == name.lower()]
    return loose[0] if len(loose) == 1 else None


def enqueue_escalation(*, client_id: str, cve_id: str, actor: str) -> bool:
    """`True` bila tugas terkirim; kegagalan broker dicatat dan tidak dilempar."""
    try:
        get_celery_client().send_task(
            TASK_NAME,
            kwargs={"client_id": client_id, "cve_id": cve_id, "actor": actor},
            queue=QUEUE,
        )
    except Exception as e:
        log.warning("cve_escalation_enqueue_failed", cve_id=cve_id, error=str(e))
        return False
    return True


def _cell(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return html.escape(text) if text else "-"


def build_escalation_email(
    *,
    cve_id: str,
    severity: str,
    score: float | None,
    kev: bool,
    exploited: bool,
    tech: str,
    ticket_id: str,
    team: str,
    plan_date: str,
    actor: str,
) -> tuple[str, str]:
    """(subject, html). Semua string luar di-`html.escape`; nilai kosong tampil "-"."""
    subject = f"[ESCALATION] {cve_id} - {severity or 'UNKNOWN'} - ticket {ticket_id or '-'}"
    rows = [
        ("CVE", cve_id),
        ("Severity", severity),
        ("CVSS score", "" if score is None else f"{score:.1f}"),
        ("CISA KEV", "Yes" if kev else "No"),
        ("Actively exploited", "Yes" if exploited else "No"),
        ("Technology", tech),
        ("Ticket", ticket_id),
        ("Owner team", team),
        ("Remediation plan date", plan_date),
        ("Escalated by", actor),
    ]
    body_rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'><b>{html.escape(label)}</b></td>"
        f"<td>{_cell(value)}</td></tr>"
        for label, value in rows
    )
    content = (
        "<html><body style='font-family:Arial,sans-serif;font-size:14px'>"
        f"<p>Ticket escalation was turned on for {_cell(cve_id)}.</p>"
        f"<table>{body_rows}</table>"
        "<p>This is a draft; review and send it from Outlook.</p></body></html>"
    )
    return subject, content
