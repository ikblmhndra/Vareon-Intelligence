"""`AsyncExecBriefRepo`: satu brief bersama per tanggal (upsert, jendela baca, purge)."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.repositories.exec_brief import AsyncExecBriefRepo
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

D = datetime.date(2026, 11, 10)
FILTERS = {"days": 7, "incident_only": False, "confirmed_only": False}


def _kw(markdown: str = "# Brief", **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "brief_date": D,
        "markdown": markdown,
        "filters": FILTERS,
        "generated_by": "scheduler",
        "model": "m1",
        "prompt_version": "abcd1234",
        "replace": False,
    }
    return base | over


async def test_insert_returns_the_row(async_db_session: AsyncSession) -> None:
    repo = AsyncExecBriefRepo(async_db_session)

    row = await repo.upsert(**_kw())  # type: ignore[arg-type]

    assert row is not None
    assert (row.brief_date, row.markdown, row.filters) == (D, "# Brief", FILTERS)
    assert row.generated_at is not None


async def test_upsert_without_replace_keeps_first_and_returns_none(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncExecBriefRepo(async_db_session)
    await repo.upsert(**_kw("pertama"))  # type: ignore[arg-type]

    again = await repo.upsert(**_kw("kedua"))  # type: ignore[arg-type]

    assert again is None
    kept = await repo.get(D)
    assert kept is not None and kept.markdown == "pertama"


async def test_upsert_replace_overwrites_and_refreshes_generated_at(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncExecBriefRepo(async_db_session)
    first = await repo.upsert(**_kw("pertama"))  # type: ignore[arg-type]
    assert first is not None
    first_at = first.generated_at

    second = await repo.upsert(  # type: ignore[arg-type]
        **_kw("kedua", replace=True, generated_by="alice", model="m2")
    )

    assert second is not None
    assert (second.markdown, second.generated_by, second.model) == ("kedua", "alice", "m2")
    assert second.generated_at >= first_at


async def test_latest_and_list_dates_window(async_db_session: AsyncSession) -> None:
    repo = AsyncExecBriefRepo(async_db_session)
    for offset in (0, -3, -7, -8):
        await repo.upsert(**_kw(f"b{offset}", brief_date=D + datetime.timedelta(days=offset)))  # type: ignore[arg-type]
    since = D - datetime.timedelta(days=7)

    dates = await repo.list_dates(since=since)
    latest = await repo.latest(since=since)

    assert dates == [D, D - datetime.timedelta(days=3), since]
    assert latest is not None and latest.brief_date == D
    assert await repo.latest(since=D + datetime.timedelta(days=1)) is None


async def test_purge_before_boundary(async_db_session: AsyncSession) -> None:
    repo = AsyncExecBriefRepo(async_db_session)
    cutoff = D - datetime.timedelta(days=30)
    for offset in (-31, -30, 0):
        await repo.upsert(**_kw(brief_date=D + datetime.timedelta(days=offset)))  # type: ignore[arg-type]

    removed = await repo.purge_before(cutoff)

    assert removed == 1
    assert await repo.list_dates(since=D - datetime.timedelta(days=60)) == [D, cutoff]


async def test_unique_brief_date(async_db_session: AsyncSession) -> None:
    from cti_core.db.models import ExecBrief

    repo = AsyncExecBriefRepo(async_db_session)
    await repo.upsert(**_kw())  # type: ignore[arg-type]

    async_db_session.add(
        ExecBrief(brief_date=D, markdown="x", filters=FILTERS, generated_by="u", model="m")
    )
    with pytest.raises(IntegrityError):
        await async_db_session.flush()
