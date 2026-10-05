"""Integration test `AsyncCveTicketRepo` + `ack_filter` wiring di
`AsyncCveTrackerRepo.list_filtered`/`get_stats`/`list_for_export` --
Postgres REAL (testcontainers). Fase 7.4 Grup C (2026-09-23)."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveTicketRepo, AsyncCveTrackerRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _ensure_clients(session: AsyncSession) -> None:
    repo = AsyncClientRepo(session)
    await repo.ensure_default()
    if await repo.get("acme") is None:
        await repo.create(client_id="acme", name="Acme", countries=[])


async def _seed_cves(session: AsyncSession, client_id: str = "default") -> None:
    session.add_all(
        [
            CveTracker(cve_id="CVE-2026-0001", client_id=client_id, tech="WordPress"),
            CveTracker(cve_id="CVE-2026-0002", client_id=client_id, tech="nginx"),
        ]
    )
    await session.flush()


# ── AsyncCveTicketRepo ────────────────────────────────────────────────────────


async def test_get_returns_none_when_missing(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)
    assert await repo.get("CVE-2026-0001", "default") is None


async def test_get_next_ticket_id_starts_at_001(async_db_session: AsyncSession) -> None:
    repo = AsyncCveTicketRepo(async_db_session)
    now = datetime.datetime.now(datetime.UTC)
    ticket_id = await repo.get_next_ticket_id()
    assert ticket_id == f"CTI-{now.year}-{now.month:02d}-001"


async def test_get_next_ticket_id_increments_and_is_global_across_clients(
    async_db_session: AsyncSession,
) -> None:
    """Port asimetri legacy -- `get_next_ticket_id()` scan lintas SEMUA
    client, bukan per-client."""
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)

    await repo.acknowledge("CVE-2026-0001", "default", "analyst1")
    second = await repo.get_next_ticket_id()
    await repo.acknowledge("CVE-2026-0002", "acme", "analyst2")
    third = await repo.get_next_ticket_id()

    now = datetime.datetime.now(datetime.UTC)
    assert second == f"CTI-{now.year}-{now.month:02d}-002"
    assert third == f"CTI-{now.year}-{now.month:02d}-003"


async def test_upsert_creates_new_ticket_with_generated_id(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)

    ticket = await repo.upsert(
        cve_id="CVE-2026-0001",
        client_id="default",
        affected_asset="web-01",
        owner_email="owner@example.com",
        escalation_required=True,
        remediation_date_plan=datetime.date(2026, 10, 1),
    )
    assert ticket.ticket_id.startswith("CTI-")
    assert ticket.affected_asset == "web-01"
    assert ticket.owner_email == "owner@example.com"
    assert ticket.escalation_required is True
    assert ticket.remediation_date_plan == datetime.date(2026, 10, 1)
    assert ticket.acknowledged_by is None


async def test_upsert_preserves_existing_ticket_id_on_update(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)

    first = await repo.upsert(cve_id="CVE-2026-0001", client_id="default", comments="v1")
    second = await repo.upsert(cve_id="CVE-2026-0001", client_id="default", comments="v2")

    assert first.ticket_id == second.ticket_id
    assert second.comments == "v2"


async def test_upsert_does_not_touch_acknowledged_by(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)

    await repo.acknowledge("CVE-2026-0001", "default", "analyst1")
    updated = await repo.upsert(cve_id="CVE-2026-0001", client_id="default", comments="edited")

    assert updated.acknowledged_by == "analyst1"
    assert updated.comments == "edited"


async def test_acknowledge_creates_ticket_when_missing(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)

    ticket = await repo.acknowledge("CVE-2026-0001", "default", "  analyst1  ")
    assert ticket.acknowledged_by == "analyst1"
    assert ticket.acknowledge_time is not None
    assert ticket.ticket_id.startswith("CTI-")


async def test_acknowledge_reuses_ticket_id_from_existing_ticket(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)

    manual = await repo.upsert(cve_id="CVE-2026-0001", client_id="default", comments="pre-ack")
    acked = await repo.acknowledge("CVE-2026-0001", "default", "analyst1")
    assert acked.ticket_id == manual.ticket_id
    assert acked.comments == "pre-ack"


async def test_get_acked_cve_ids_and_ack_statuses(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)
    await repo.upsert(cve_id="CVE-2026-0001", client_id="default", comments="not acked")
    await repo.acknowledge("CVE-2026-0002", "default", "analyst1")

    acked_ids = await repo.get_acked_cve_ids("default")
    assert acked_ids == ["CVE-2026-0002"]

    statuses = await repo.get_ack_statuses("default")
    assert statuses == {"CVE-2026-0002": "analyst1"}


async def test_bulk_acknowledge_skips_already_acked_and_assigns_distinct_ticket_ids(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)
    await repo.acknowledge("CVE-2026-0001", "default", "analyst1")

    count = await repo.bulk_acknowledge(["CVE-2026-0001", "CVE-2026-0002"], "default", "analyst2")
    assert count == 1  # CVE-2026-0001 udah acked, di-skip

    t1 = await repo.get("CVE-2026-0001", "default")
    t2 = await repo.get("CVE-2026-0002", "default")
    assert t1 is not None and t2 is not None
    assert t1.acknowledged_by == "analyst1"  # gak keganti
    assert t2.acknowledged_by == "analyst2"
    assert t1.ticket_id != t2.ticket_id


async def test_bulk_acknowledge_assigns_sequential_ids_for_multiple_new_tickets(
    async_db_session: AsyncSession,
) -> None:
    """Regression: dua CVE baru dalam SATU batch gak boleh kebagian
    ticket_id yang sama -- butuh flush per-iterasi, lihat docstring repo."""
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)

    count = await repo.bulk_acknowledge(["CVE-2026-0001", "CVE-2026-0002"], "default", "analyst1")
    assert count == 2

    t1 = await repo.get("CVE-2026-0001", "default")
    t2 = await repo.get("CVE-2026-0002", "default")
    assert t1 is not None and t2 is not None
    assert t1.ticket_id != t2.ticket_id


async def test_bulk_acknowledge_returns_zero_when_all_already_acked(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)
    await repo.acknowledge("CVE-2026-0001", "default", "analyst1")

    count = await repo.bulk_acknowledge(["CVE-2026-0001"], "default", "analyst2")
    assert count == 0


# ── ack_filter wiring (AsyncCveTrackerRepo) ──────────────────────────────────


async def test_list_filtered_ack_filter_acked_and_unacked(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_cves(async_db_session)
    await AsyncCveTicketRepo(async_db_session).acknowledge("CVE-2026-0001", "default", "a1")

    tracker_repo = AsyncCveTrackerRepo(async_db_session)
    acked, acked_total = await tracker_repo.list_filtered(client_id="default", ack_filter="acked")
    assert acked_total == 1
    assert acked[0].cve_id == "CVE-2026-0001"

    unacked, unacked_total = await tracker_repo.list_filtered(
        client_id="default", ack_filter="unacked"
    )
    assert unacked_total == 1
    assert unacked[0].cve_id == "CVE-2026-0002"


async def test_list_filtered_ack_filter_scoped_per_client(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_cves(async_db_session, client_id="acme")
    # acknowledge di client "default" -- CVE-2026-0001 gak ada di client
    # "default", jadi ack_filter="acked" buat client "acme" harus TETAP
    # kosong (acknowledge-nya nempel client lain).
    await AsyncClientRepo(async_db_session).ensure_default()
    session = async_db_session
    session.add(CveTracker(cve_id="CVE-2026-0001", client_id="default", tech="WordPress"))
    await session.flush()
    await AsyncCveTicketRepo(session).acknowledge("CVE-2026-0001", "default", "a1")

    tracker_repo = AsyncCveTrackerRepo(session)
    _acked_acme, total_acme = await tracker_repo.list_filtered(client_id="acme", ack_filter="acked")
    assert total_acme == 0


async def test_get_stats_ack_filter(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_cves(async_db_session)
    await AsyncCveTicketRepo(async_db_session).acknowledge("CVE-2026-0001", "default", "a1")

    stats = await AsyncCveTrackerRepo(async_db_session).get_stats(
        client_id="default", ack_filter="acked"
    )
    assert stats["total"] == 1


async def test_list_for_export_filters_by_detected_on_not_published(
    async_db_session: AsyncSession,
) -> None:
    """`list_for_export` filter tanggal di `detected_on`, beda dari
    `list_filtered` yang filter `published` -- asimetri legacy
    dipertahankan apa adanya (lihat docstring repo)."""
    await _ensure_clients(async_db_session)
    old_detected = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
    async_db_session.add_all(
        [
            CveTracker(
                cve_id="CVE-2026-0001",
                client_id="default",
                tech="WordPress",
                published=datetime.date(2026, 9, 1),
                detected_on=old_detected,
            ),
        ]
    )
    await async_db_session.flush()

    # filter by `published` (list_filtered) MATCH -- tapi filter by
    # `detected_on` (list_for_export) TIDAK, karena detected_on-nya lama.
    _filtered, total = await AsyncCveTrackerRepo(async_db_session).list_filtered(
        client_id="default", date_start=datetime.date(2026, 9, 1)
    )
    assert total == 1

    exported = await AsyncCveTrackerRepo(async_db_session).list_for_export(
        client_id="default", date_start=datetime.date(2026, 9, 1)
    )
    assert exported == []


async def test_list_for_export_respects_exclude_and_ack_filter(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    await _seed_cves(async_db_session)
    await AsyncCveTicketRepo(async_db_session).acknowledge("CVE-2026-0001", "default", "a1")

    result = await AsyncCveTrackerRepo(async_db_session).list_for_export(
        client_id="default", exclude_cve_ids=["CVE-2026-0002"], ack_filter="acked"
    )
    assert [c.cve_id for c in result] == ["CVE-2026-0001"]


async def test_ticket_list_with_cve_filters_and_scopes_client(async_db_session: AsyncSession) -> None:
    """`list_with_cve` -- view Ticketing: join ke CVE, filter status/search,
    scope per-client."""
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)
    async_db_session.add(CveTracker(cve_id="CVE-2026-7001", client_id="default", tech="nginx"))
    await async_db_session.flush()
    await repo.upsert(cve_id="CVE-2026-7001", client_id="default", remediation_status="Open")
    await repo.upsert(cve_id="CVE-2026-7002", client_id="default")  # CVE yatim + tanpa status

    all_rows = await repo.list_with_cve("default")
    assert {t.cve_id for t, _ in all_rows} == {"CVE-2026-7001", "CVE-2026-7002"}
    joined = {t.cve_id: c for t, c in all_rows}
    assert joined["CVE-2026-7001"] is not None and joined["CVE-2026-7002"] is None

    opened = await repo.list_with_cve("default", status="Open")
    assert [t.cve_id for t, _ in opened] == ["CVE-2026-7001"]
    no_status = await repo.list_with_cve("default", status="__none__")
    assert [t.cve_id for t, _ in no_status] == ["CVE-2026-7002"]
    assert await repo.list_with_cve("other-client") == []
