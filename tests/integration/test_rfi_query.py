"""Integration test `AsyncRFIRepo` -- Postgres REAL (testcontainers).
Fase 7.3 (router `rfi`, Bagian 2)."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.rfi import AsyncRFIRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _ensure_clients(session: AsyncSession) -> None:
    repo = AsyncClientRepo(session)
    await repo.ensure_default()
    if await repo.get("acme") is None:
        await repo.create(client_id="acme", name="Acme", countries=[])


async def test_create_and_list(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncRFIRepo(async_db_session)

    rfi = await repo.create(
        {"requester": "analyst1", "question": "Any IOC for APT41?"}, client_id="default"
    )
    assert rfi.status == "open"
    assert rfi.response == ""

    rfis, total = await repo.list_filtered(client_id="default")
    assert total == 1
    assert rfis[0].id == rfi.id


async def test_list_filtered_by_status(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncRFIRepo(async_db_session)
    await repo.create({"requester": "a1", "question": "q1", "status": "open"}, client_id="default")
    await repo.create(
        {"requester": "a2", "question": "q2", "status": "closed"}, client_id="default"
    )

    open_rfis, total_open = await repo.list_filtered(client_id="default", status="open")
    assert total_open == 1
    assert open_rfis[0].status == "open"


async def test_list_filtered_scoped_by_client(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncRFIRepo(async_db_session)
    await repo.create({"requester": "a1", "question": "q1"}, client_id="default")
    await repo.create({"requester": "a2", "question": "q2"}, client_id="acme")

    _, total_default = await repo.list_filtered(client_id="default")
    _, total_acme = await repo.list_filtered(client_id="acme")
    assert total_default == 1
    assert total_acme == 1


async def test_get_by_id_scoped_by_client_returns_none_for_wrong_client(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncRFIRepo(async_db_session)
    rfi = await repo.create({"requester": "a1", "question": "q1"}, client_id="default")

    assert await repo.get_by_id(rfi.id, "default") is not None
    assert await repo.get_by_id(rfi.id, "acme") is None


async def test_update_ignores_client_scope(async_db_session: AsyncSession) -> None:
    """Port apa adanya: `update_rfi` lama gak nge-filter client_id sama
    sekali -- beda dari `list`/`get`/`create` di file yang sama. Lihat
    docstring modul `cti_core.db.repositories.rfi`."""
    await _ensure_clients(async_db_session)
    repo = AsyncRFIRepo(async_db_session)
    rfi = await repo.create({"requester": "a1", "question": "q1"}, client_id="default")

    updated = await repo.update(rfi.id, {"status": "in_progress", "response": "checking"})
    assert updated is not None
    assert updated.status == "in_progress"
    assert updated.response == "checking"


async def test_update_missing_returns_none(async_db_session: AsyncSession) -> None:
    repo = AsyncRFIRepo(async_db_session)
    assert await repo.update(999999, {"status": "closed"}) is None


async def test_delete_ignores_client_scope(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncRFIRepo(async_db_session)
    rfi = await repo.create({"requester": "a1", "question": "q1"}, client_id="default")

    assert await repo.delete(rfi.id) is True
    assert await repo.get_by_id_unscoped(rfi.id) is None


async def test_delete_missing_returns_false(async_db_session: AsyncSession) -> None:
    repo = AsyncRFIRepo(async_db_session)
    assert await repo.delete(999999) is False


async def test_linked_pir_fk_set_null_on_pir_delete(async_db_session: AsyncSession) -> None:
    """`linked_pir_id` FK asli (`ondelete=SET NULL`) -- beda dari kode
    lama yang cuma nyimpen string ObjectId lepas tanpa validasi apa pun."""
    from cti_core.db.repositories.pir import AsyncPIRRepo

    await _ensure_clients(async_db_session)
    pir_repo = AsyncPIRRepo(async_db_session)
    pir = await pir_repo.create({"title": "Track APT41"}, client_id="default")

    rfi_repo = AsyncRFIRepo(async_db_session)
    rfi = await rfi_repo.create(
        {"requester": "a1", "question": "q1", "linked_pir": pir.id}, client_id="default"
    )
    assert rfi.linked_pir_id == pir.id

    await pir_repo.delete(pir.id)
    await async_db_session.refresh(rfi)
    assert rfi.linked_pir_id is None


async def test_create_with_due_date(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncRFIRepo(async_db_session)
    rfi = await repo.create(
        {"requester": "a1", "question": "q1", "due_date": datetime.date(2026, 10, 1)},
        client_id="default",
    )
    assert rfi.due_date == datetime.date(2026, 10, 1)


async def test_status_counts_per_client(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncRFIRepo(async_db_session)
    await repo.create({"requester": "a", "question": "q1", "status": "open"}, client_id="default")
    await repo.create({"requester": "a", "question": "q2", "status": "open"}, client_id="default")
    await repo.create({"requester": "a", "question": "q3", "status": "closed"}, client_id="default")
    await repo.create({"requester": "a", "question": "q4", "status": "open"}, client_id="acme")

    counts = await repo.status_counts("default")
    assert counts == {"open": 2, "in_progress": 0, "closed": 1}


async def test_status_counts_filter_independent(async_db_session: AsyncSession) -> None:
    """Hitungan status untuk chip UI tidak ikut menyempit saat daftar difilter `status`."""
    await _ensure_clients(async_db_session)
    repo = AsyncRFIRepo(async_db_session)
    for st in ("open", "in_progress", "closed"):
        await repo.create({"requester": "a", "question": st, "status": st}, client_id="default")

    rfis, total = await repo.list_filtered(client_id="default", status="closed")
    assert total == 1 and rfis[0].status == "closed"
    assert await repo.status_counts("default") == {"open": 1, "in_progress": 1, "closed": 1}


async def test_status_counts_unknown_status_ignored(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncRFIRepo(async_db_session)
    await repo.create({"requester": "a", "question": "q", "status": "weird"}, client_id="default")

    assert await repo.status_counts("default") == {"open": 0, "in_progress": 0, "closed": 0}


async def test_search_and_linked_pir_filter(async_db_session: AsyncSession) -> None:
    from cti_core.db.repositories.pir import AsyncPIRRepo

    await _ensure_clients(async_db_session)
    pir = await AsyncPIRRepo(async_db_session).create({"title": "P"}, client_id="default")
    repo = AsyncRFIRepo(async_db_session)
    r1 = await repo.create(
        {"requester": "Alice", "question": "Any LockBit infra?", "linked_pir": pir.id},
        client_id="default",
    )
    r2 = await repo.create({"requester": "bob", "question": "100% done?"}, client_id="default")

    by_question, _ = await repo.list_filtered(client_id="default", q="lockbit")
    assert [r.id for r in by_question] == [r1.id]
    by_requester, _ = await repo.list_filtered(client_id="default", q="BOB")
    assert [r.id for r in by_requester] == [r2.id]
    literal, total = await repo.list_filtered(client_id="default", q="%")
    assert total == 1 and literal[0].id == r2.id
    linked, total = await repo.list_filtered(client_id="default", linked_pir=pir.id)
    assert total == 1 and linked[0].id == r1.id


async def test_status_counts_respect_q_and_linked_pir(async_db_session: AsyncSession) -> None:
    """Chip status harus cocok dengan daftar yang sedang dicari/disaring PIR (tab "open" di link
    PIR menunjukkan angka PIR itu saja), tapi tetap tidak ikut filter `status`."""
    from cti_core.db.repositories.pir import AsyncPIRRepo

    await _ensure_clients(async_db_session)
    pir = await AsyncPIRRepo(async_db_session).create({"title": "P"}, client_id="default")
    repo = AsyncRFIRepo(async_db_session)
    await repo.create(
        {"requester": "a", "question": "LockBit infra", "status": "open", "linked_pir": pir.id},
        client_id="default",
    )
    await repo.create(
        {"requester": "a", "question": "LockBit TTPs", "status": "in_progress"},
        client_id="default",
    )
    await repo.create(
        {"requester": "a", "question": "Akira", "status": "closed", "linked_pir": pir.id},
        client_id="default",
    )

    assert await repo.status_counts("default", q="lockbit") == {
        "open": 1,
        "in_progress": 1,
        "closed": 0,
    }
    assert await repo.status_counts("default", linked_pir=pir.id) == {
        "open": 1,
        "in_progress": 0,
        "closed": 1,
    }
    assert await repo.status_counts("default", q="lockbit", linked_pir=pir.id) == {
        "open": 1,
        "in_progress": 0,
        "closed": 0,
    }


async def test_sort_due(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncRFIRepo(async_db_session)
    none1 = await repo.create({"requester": "a", "question": "n1"}, client_id="default")
    late = await repo.create(
        {"requester": "a", "question": "late", "due_date": datetime.date(2026, 12, 1)},
        client_id="default",
    )
    soon_a = await repo.create(
        {"requester": "a", "question": "sa", "due_date": datetime.date(2026, 11, 1)},
        client_id="default",
    )
    soon_b = await repo.create(
        {"requester": "a", "question": "sb", "due_date": datetime.date(2026, 11, 1)},
        client_id="default",
    )
    none2 = await repo.create({"requester": "a", "question": "n2"}, client_id="default")

    rfis, _ = await repo.list_filtered(client_id="default", sort="due")
    assert [r.id for r in rfis] == [soon_a.id, soon_b.id, late.id, none1.id, none2.id]
