"""Integration test `AsyncCveTicketRepo` + `ack_filter` wiring di
`AsyncCveTrackerRepo.list_filtered`/`get_stats`/`list_for_export` --
Postgres REAL (testcontainers). Fase 7.4 Grup C (2026-09-23)."""

from __future__ import annotations

import asyncio
import datetime
import zoneinfo

import pytest
from cti_core.db.models.auth import Client
from cti_core.db.models.cve import CveTicket, CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveTicketRepo, AsyncCveTrackerRepo
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    now = datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Jakarta"))
    ticket_id = await repo.get_next_ticket_id()
    assert ticket_id == f"CTI-{now.year}-{now.month:02d}-001"


async def test_get_next_ticket_id_month_follows_wib_not_utc(
    async_db_session: AsyncSession,
) -> None:
    """01.00 WIB tgl 1 Oktober masih 30 September di UTC. Dashboard dan export membaca hari
    kalender WIB, jadi nomor ticketnya juga harus bulan WIB."""
    repo = AsyncCveTicketRepo(async_db_session)
    utc_evening = datetime.datetime(2026, 9, 30, 18, 0, tzinfo=datetime.UTC)  # 01.00 WIB 1 Okt
    assert await repo.get_next_ticket_id(now=utc_evening) == "CTI-2026-10-001"


async def test_tracking_id_for_joins_existing_ticket_ids_of_the_clients_cves(
    async_db_session: AsyncSession,
) -> None:
    """Email CVE harus memuat nomor ticket yang sudah ada di CVE-nya, bukan nomor 'intipan' baru
    yang tidak pernah disimpan."""
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)
    first = await repo.acknowledge("CVE-2026-0601", "default", "analyst1")
    second = await repo.acknowledge("CVE-2026-0602", "default", "analyst1")
    await repo.acknowledge("CVE-2026-0603", "acme", "analyst1")  # client lain, diabaikan

    tracking = await repo.tracking_id_for(
        ["CVE-2026-0601", "CVE-2026-0602", "CVE-2026-0603", "CVE-2026-0604"], "default"
    )
    assert tracking == f"{first.ticket_id}, {second.ticket_id}"
    assert await repo.tracking_id_for(["CVE-2026-0604"], "default") is None


async def _overlap_transactions(first_op, second_op, cve_ids, before=None):  # type: ignore[no-untyped-def]
    """Jalankan dua operasi ticket di dua transaksi yang benar-benar commit dan saling tumpang
    tindih: yang pertama sudah flush tapi belum commit saat yang kedua mulai. Mengembalikan hasil
    keduanya (exception ikut naik). Fixture lain di-rollback, jadi bersih-bersih di sini.
    `before` (opsional): di-commit lebih dulu, mis. menyimpan ticket yang kemudian di-ack."""
    from cti_core.db.engine import get_async_engine

    maker = async_sessionmaker(get_async_engine(), expire_on_commit=False)
    async with maker() as setup:
        created_default = await AsyncClientRepo(setup).get("default") is None
        await AsyncClientRepo(setup).ensure_default()
        if before is not None:
            await before(AsyncCveTicketRepo(setup))
        await setup.commit()

    first_flushed = asyncio.Event()
    release_first = asyncio.Event()

    async def first():  # type: ignore[no-untyped-def]
        async with maker() as s:
            result = await first_op(AsyncCveTicketRepo(s))
            first_flushed.set()
            await release_first.wait()  # tahan commit: yang kedua harus menunggu, bukan menyalip
            await s.commit()
            return result

    async def second():  # type: ignore[no-untyped-def]
        await first_flushed.wait()
        async with maker() as s:
            result = await second_op(AsyncCveTicketRepo(s))
            await s.commit()
            return result

    try:
        t1, t2 = asyncio.create_task(first()), asyncio.create_task(second())
        await first_flushed.wait()
        await asyncio.sleep(0.3)
        release_first.set()
        return await asyncio.gather(t1, t2)
    finally:
        async with maker() as cleanup:
            await cleanup.execute(delete(CveTicket).where(CveTicket.cve_id.in_(cve_ids)))
            if created_default:
                await cleanup.execute(delete(Client).where(Client.client_id == "default"))
            await cleanup.commit()


async def test_concurrent_ticket_creation_gets_distinct_ids(_migrated_schema: None) -> None:
    """Dua transaksi yang membuat ticket bersamaan tidak boleh mendapat nomor yang sama (dulu:
    keduanya membaca max yang sama, lalu yang kedua gagal `IntegrityError` -> 500)."""
    first, second = await _overlap_transactions(
        lambda repo: repo.acknowledge("CVE-2099-0001", "default", "a"),
        lambda repo: repo.acknowledge("CVE-2099-0002", "default", "b"),
        ("CVE-2099-0001", "CVE-2099-0002"),
    )
    assert first.ticket_id != second.ticket_id


_FIRST_TIME_OPS = {
    "ack": lambda repo: repo.acknowledge("CVE-2099-0003", "default", "x"),
    "save": lambda repo: repo.upsert(cve_id="CVE-2099-0003", client_id="default", owner_team="t"),
    "bulk": lambda repo: repo.bulk_acknowledge(["CVE-2099-0003"], "default", "x"),
}


@pytest.mark.parametrize("second", ["ack", "save", "bulk"])
@pytest.mark.parametrize("first", ["ack", "save", "bulk"])
async def test_concurrent_first_time_ticket_for_same_cve_does_not_collide(
    _migrated_schema: None, first: str, second: str
) -> None:
    """Pemeriksaan 'ticket sudah ada' harus diulang SETELAH lock penomoran didapat: transaksi
    kedua menunggu lock, dan ticket yang dibuat transaksi pertama sudah ada saat ia lanjut. Tanpa
    itu keduanya menyisipkan baris `(cve_id, client_id)` sama dan satu kena `IntegrityError`."""
    results = await _overlap_transactions(
        _FIRST_TIME_OPS[first], _FIRST_TIME_OPS[second], ("CVE-2099-0003",)
    )
    ticket_ids = {r.ticket_id for r in results if isinstance(r, CveTicket)}
    assert len(ticket_ids) <= 1


async def test_concurrent_acknowledgements_of_one_ticket_keep_the_first(
    _migrated_schema: None,
) -> None:
    """Dua analis meng-ack CVE yang sama bersamaan (ticket sudah disimpan, belum di-ack): yang
    pertama menang. Transaksi kedua harus menunggu lock lalu melihat ack yang sudah ter-commit;
    kalau ia membaca 'belum di-ack' sebelum yang pertama commit, ia menimpanya."""
    first, second = await _overlap_transactions(
        lambda repo: repo.acknowledge("CVE-2099-0004", "default", "first"),
        lambda repo: repo.acknowledge("CVE-2099-0004", "default", "second"),
        ("CVE-2099-0004",),
        before=lambda repo: repo.upsert(
            cve_id="CVE-2099-0004", client_id="default", comments="saved"
        ),
    )
    assert (first.acknowledged_by, second.acknowledged_by) == ("first", "first")


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


async def test_acknowledging_again_keeps_the_first_acknowledgement(
    async_db_session: AsyncSession,
) -> None:
    """Ack pertama menang (sama dengan `bulk_acknowledge`): nama, waktu ack (dasar MTTA), dan nomor
    ticket tidak berubah. Dulu ack ulang menimpa ketiganya."""
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)

    ticket = await repo.acknowledge("CVE-2026-0001", "default", "analyst1")
    kept = (ticket.acknowledged_by, ticket.acknowledge_time, ticket.ticket_id)
    again = await repo.acknowledge("CVE-2026-0001", "default", "analyst2")

    assert (again.acknowledged_by, again.acknowledge_time, again.ticket_id) == kept


async def test_acknowledge_is_judged_per_client(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)

    await repo.acknowledge("CVE-2026-0001", "default", "analyst1")
    other = await repo.acknowledge("CVE-2026-0001", "acme", "analyst2")

    assert other.acknowledged_by == "analyst2"


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


async def test_bulk_acknowledge_ignores_duplicate_cve_ids(async_db_session: AsyncSession) -> None:
    """`cve_ids` yang sama dua kali (mis. `CVE-X` dan `cve-x` setelah dinormalisasi) dihitung
    sekali: dulu iterasi kedua menyisipkan ticket `(cve_id, client_id)` kedua dan kena
    `IntegrityError`."""
    await _ensure_clients(async_db_session)
    repo = AsyncCveTicketRepo(async_db_session)

    acknowledged = await repo.bulk_acknowledge(
        ["CVE-2026-0701", "CVE-2026-0701", "CVE-2026-0702"], "default", "analyst1"
    )

    assert acknowledged == 2
    assert sorted(await repo.get_acked_cve_ids("default")) == ["CVE-2026-0701", "CVE-2026-0702"]


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


async def test_ticket_list_with_cve_filters_and_scopes_client(
    async_db_session: AsyncSession,
) -> None:
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
