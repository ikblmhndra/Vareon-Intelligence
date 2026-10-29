"""Query feed bersama (P7b): TLP, settle lag, keyset paging, filter. Postgres REAL."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services import feed
from cti_core.db.models.indicator import Indicator
from cti_core.indicator.stix_id import indicator_uuid
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _add(
    session: AsyncSession, value: str, *, type: str = "domain", **kw: object
) -> Indicator:
    ind = Indicator(
        type=type,
        value=value,
        stix_id=indicator_uuid(type, value),
        **kw,  # type: ignore[arg-type]
    )
    session.add(ind)
    await session.flush()
    return ind


async def _back(session: AsyncSession, ind: Indicator, when: datetime.datetime) -> None:
    await session.execute(
        update(Indicator).where(Indicator.id == ind.id).values(feed_changed_at=when)
    )
    await session.refresh(ind)


@pytest.fixture(autouse=True)
def _no_lag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feed, "FEED_SETTLE_SECONDS", 0)


async def test_tlp_filter(async_db_session: AsyncSession) -> None:
    for tlp in ("clear", "green", "amber"):
        await _add(async_db_session, f"{tlp}.example.com", tlp=tlp)
    clear = await feed.feed_page(async_db_session, max_tlp="clear", limit=10)
    assert {i.tlp for i in clear.items} == {"clear"}
    amber = await feed.feed_page(async_db_session, max_tlp="amber", limit=10)
    assert {i.tlp for i in amber.items} == {"clear", "green", "amber"}


async def test_settle_lag_hides_fresh_rows(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(feed, "FEED_SETTLE_SECONDS", 60)
    fresh = await _add(async_db_session, "fresh.example.com")
    old = await _add(async_db_session, "old.example.com")
    await _back(
        async_db_session, old, datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=2)
    )
    page = await feed.feed_page(async_db_session, max_tlp="red", limit=10)
    ids = {i.id for i in page.items}
    assert old.id in ids and fresh.id not in ids


async def test_page_ties(async_db_session: AsyncSession) -> None:
    rows = [await _add(async_db_session, f"t{n}.example.com") for n in range(7)]
    seen: list[int] = []
    after = None
    sizes = []
    for _ in range(5):
        page = await feed.feed_page(async_db_session, max_tlp="red", limit=3, after=after)
        sizes.append(len(page.items))
        seen += [i.id for i in page.items]
        if page.next_cursor is None:
            break
        after = feed.decode_cursor(page.next_cursor)
    assert sizes == [3, 3, 1]
    assert sorted(seen) == sorted(r.id for r in rows) and len(set(seen)) == 7
    assert page.next_cursor is None


async def test_changed_after_strict(async_db_session: AsyncSession) -> None:
    a = await _add(async_db_session, "a.example.com")
    b = await _add(async_db_session, "b.example.com")
    t0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    await _back(async_db_session, a, t0)
    await _back(async_db_session, b, t0 + datetime.timedelta(seconds=1))
    page = await feed.feed_page(async_db_session, max_tlp="red", limit=10, changed_after=t0)
    assert [i.id for i in page.items] == [b.id]


async def test_state_and_type_filters(async_db_session: AsyncSession) -> None:
    now = datetime.datetime.now(datetime.UTC)
    active = await _add(async_db_session, "act.example.com")
    revoked = await _add(async_db_session, "rev.example.com", revoked_at=now)
    ip = await _add(async_db_session, "10.0.0.1", type="ip")
    page = await feed.feed_page(async_db_session, max_tlp="red", limit=10, states={"revoked"})
    assert [i.id for i in page.items] == [revoked.id]
    page = await feed.feed_page(async_db_session, max_tlp="red", limit=10, types={"ip"})
    assert [i.id for i in page.items] == [ip.id]
    page = await feed.feed_page(async_db_session, max_tlp="red", limit=10, states=None)
    assert {active.id, revoked.id, ip.id} <= {i.id for i in page.items}


async def test_stix_ids_filter(async_db_session: AsyncSession) -> None:
    a = await _add(async_db_session, "a.example.com")
    await _add(async_db_session, "b.example.com")
    assert a.stix_id is not None
    page = await feed.feed_page(async_db_session, max_tlp="red", limit=10, stix_ids=[a.stix_id])
    assert [i.id for i in page.items] == [a.id]
