"""Query feed bersama (P7b): TLP, settle lag, keyset paging, filter. Postgres REAL."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from cti_api.services import feed
from cti_core.db.models.entity import Entity, Relationship
from cti_core.db.models.indicator import Indicator
from cti_core.db.models.story import Story
from cti_core.indicator.stix_id import indicator_uuid
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration import intel_support

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
    monkeypatch.setattr(feed, "FEED_SETTLE_SECONDS", -5)  # clock_timestamp() > now() in test tx


async def test_tlp_filter(async_db_session: AsyncSession) -> None:
    levels = ("clear", "green", "amber", "amber+strict", "red")
    for n, tlp in enumerate(levels):
        await _add(async_db_session, f"t{n}.example.com", tlp=tlp)
    for max_tlp, expected in [
        ("clear", {"clear"}),
        ("amber", {"clear", "green", "amber"}),
        ("amber+strict", {"clear", "green", "amber", "amber+strict"}),
        ("red", set(levels)),
    ]:
        page = await feed.feed_page(async_db_session, max_tlp=max_tlp, limit=10)
        assert {i.tlp for i in page.items} == expected, max_tlp


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


async def test_stix_ids_lookup_skips_settle_lag(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(feed, "FEED_SETTLE_SECONDS", 60)
    fresh = await _add(async_db_session, "fresh-by-id.example.com")
    assert fresh.stix_id is not None
    listing = await feed.feed_page(async_db_session, max_tlp="red", limit=10)
    assert fresh.id not in {i.id for i in listing.items}
    by_id = await feed.feed_page(
        async_db_session, max_tlp="red", limit=10, stix_ids=[fresh.stix_id]
    )
    assert [i.id for i in by_id.items] == [fresh.id]


# ── Feed intel gabungan (P7c Task 15) ───────────────────────────────────────


def _intel_labels(g: Any, objs: list[dict[str, Any]]) -> list[str]:
    back = {v: k for k, v in g.ids.items()}
    return [back.get(o["id"], o["id"]) for o in objs]


async def _intel_all(
    session: AsyncSession, limit: int, max_tlp: str = "clear"
) -> tuple[list[dict[str, Any]], list[str]]:
    objs: list[dict[str, Any]] = []
    cursors: list[str] = []
    after = None
    while True:
        page = await feed.intel_feed_page(
            session,
            max_tlp=max_tlp,
            limit=limit,
            types=None,
            changed_after=None if after else intel_support.BASE - datetime.timedelta(days=1),
            after=after,
            stix_ids=None,
        )
        objs += page.objects
        if page.next_cursor is None:
            return objs, cursors
        cursors.append(page.next_cursor)
        after = feed.decode_intel_cursor(page.next_cursor)


@pytest.mark.parametrize("limit", [1, 2, 3, 4, 7, 8, 50])
async def test_intel_paging_deterministic(async_db_session: AsyncSession, limit: int) -> None:
    g = await intel_support.seed_graph(async_db_session)
    objs, cursors = await _intel_all(async_db_session, limit)
    assert _intel_labels(g, objs) == intel_support.CLEAR_ORDER
    again, cursors2 = await _intel_all(async_db_session, limit)
    assert again == objs and cursors2 == cursors


async def test_intel_cursor_roundtrip_and_rejects_garbage() -> None:
    ts = datetime.datetime(2020, 1, 1, 0, 0, 0, 123456, tzinfo=datetime.UTC)
    for kind in ("entity", "relationship", "indicator", "report"):
        assert feed.decode_intel_cursor(feed.encode_intel_cursor(ts, kind, 7)) == (ts, kind, 7)
    for bad in ("", "zz", feed.encode_cursor(ts, 7), feed.encode_intel_cursor(ts, "x", 7)):
        with pytest.raises(ValueError):
            feed.decode_intel_cursor(bad)


async def test_intel_settle_lag_every_kind(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = await intel_support.seed_graph(async_db_session)
    monkeypatch.setattr(feed, "FEED_SETTLE_SECONDS", 60)
    for model, label in (
        (Entity, "M"), (Relationship, "R1"), (Indicator, "I"), (Story, "S1"),
    ):  # fmt: skip
        await async_db_session.execute(
            update(model)  # type: ignore[arg-type]
            .where(model.id == g.rows[label])  # type: ignore[attr-defined]
            .values(feed_changed_at=func.clock_timestamp())
        )
    page = await feed.intel_feed_page(
        async_db_session, max_tlp="clear", limit=50, types=None,
        changed_after=intel_support.BASE - datetime.timedelta(days=1), after=None, stix_ids=None,
    )  # fmt: skip
    assert _intel_labels(g, page.objects) == ["A", "T", "R3", "R4"]
    by_id = await feed.intel_feed_page(
        async_db_session, max_tlp="clear", limit=50, types=None, changed_after=None, after=None,
        stix_ids=[g.ids["M"], g.ids["S1"]],
    )  # fmt: skip
    assert sorted(_intel_labels(g, by_id.objects)) == ["M", "S1"]
