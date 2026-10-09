"""`POST /api/cve/purge-orphaned` tidak pernah menghapus baris tracker yang punya ticket atau ack.

Ticket berkunci `(cve_id, client_id)` dan tidak ber-FK ke tracker, jadi menghapus barisnya
meninggalkan ticket yatim dan menghapus riwayat remediasi dari dashboard (MTTA dan MTTR dihitung
dari baris tracker yang punya ticket). Definisi "dilindungi" sama dengan
`tools/ops/reconcile_cve_tech.py` (ada ticket untuk `(cve_id, client_id)`-nya)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.cve import CveTracker
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

KEPT = "CVE-2026-0701"
DROPPED = "CVE-2026-0702"


async def test_purge_keeps_ticketed_rows_reports_them_and_leaves_the_ticket_intact(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    # Client tanpa entri techstack: tab tanpa filter, dan semua baris dianggap yatim oleh purge.
    api_session.add_all(
        CveTracker(cve_id=c, client_id="default", tech="gone") for c in (KEPT, DROPPED)
    )
    await api_session.flush()
    admin = auth_header(username="admin1", role="admin")
    await api_client.post(f"/api/cve/{KEPT}/acknowledge", headers=admin)

    preview = (
        await api_client.post("/api/cve/purge-orphaned", headers=admin, json={"dry_run": True})
    ).json()
    assert (preview["would_delete"], preview["cve_ids"]) == (1, [DROPPED])
    assert (preview["protected"], preview["protected_cve_ids"]) == (1, [KEPT])

    executed = (
        await api_client.post("/api/cve/purge-orphaned", headers=admin, json={"dry_run": False})
    ).json()
    assert (executed["dry_run"], executed["deleted"], executed["protected"]) == (False, 1, 1)

    tab = (await api_client.get("/api/cve", headers=admin)).json()
    assert [c["cve_id"] for c in tab["cves"]] == [KEPT]
    ticket = (await api_client.get(f"/api/cve/{KEPT}/ticket", headers=admin)).json()
    assert ticket["acknowledged_by"] == "admin1"

    audit = (
        await api_session.execute(
            select(AuditLogEntry.detail).where(AuditLogEntry.action == "purge_orphaned_cves")
        )
    ).scalar_one()
    assert audit == {"deleted": 1, "by_tech": {"gone": 1}, "protected": 1}
