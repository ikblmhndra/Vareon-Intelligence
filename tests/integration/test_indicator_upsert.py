"""Aturan ingest indikator (spec P7a 3.2): validitas diperpanjang, revokasi dan marking dijaga."""

from __future__ import annotations

import datetime

from cti_core.db.models.indicator import Indicator, IndicatorSource
from cti_core.db.repositories.indicator import AsyncIndicatorRepo, IndicatorRepo
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_DAY = datetime.timedelta(days=1)
_SLOP = datetime.timedelta(minutes=1)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _up(repo: IndicatorRepo, type: str, value: str, **kw: str) -> Indicator:
    return repo.upsert(type=type, value=value, source_url="https://s/1", source_name="s", **kw)


def test_new_ip_gets_ttl(db_session: Session) -> None:
    ind = _up(IndicatorRepo(db_session), "ip", "198.51.100.1")
    assert abs(ind.valid_from - _now()) < _SLOP
    assert abs(ind.valid_until - (_now() + 30 * _DAY)) < _SLOP


def test_new_hash_never_expires(db_session: Session) -> None:
    assert _up(IndicatorRepo(db_session), "md5", "a" * 32).valid_until is None


def test_upsert_reactivates_expired(db_session: Session) -> None:
    repo = IndicatorRepo(db_session)
    ind = _up(repo, "ip", "198.51.100.2")
    start = ind.valid_from
    ind.valid_until = _now() - 10 * _DAY
    assert ind.state == "expired"
    _up(repo, "ip", "198.51.100.2")
    assert ind.state == "active"
    assert abs(ind.valid_until - (_now() + 30 * _DAY)) < _SLOP
    assert ind.valid_from == start


def test_upsert_keeps_revocation(db_session: Session) -> None:
    repo = IndicatorRepo(db_session)
    ind = _up(repo, "domain", "revoked.example")
    revoked_at = _now() - _DAY
    ind.revoked_at = revoked_at
    _up(repo, "domain", "revoked.example")
    assert ind.revoked_at == revoked_at
    assert ind.state == "revoked"
    n = db_session.execute(
        select(func.count())
        .select_from(IndicatorSource)
        .where(IndicatorSource.indicator_id == ind.id)
    ).scalar_one()
    assert n == 2


def test_marking_only_goes_up(db_session: Session) -> None:
    repo = IndicatorRepo(db_session)
    amber = _up(repo, "ip", "198.51.100.3", tlp="amber", pap="amber")
    _up(repo, "ip", "198.51.100.3")
    assert (amber.tlp, amber.pap) == ("amber", "amber")
    clear = _up(repo, "ip", "198.51.100.4")
    _up(repo, "ip", "198.51.100.4", tlp="green", pap="green")
    assert (clear.tlp, clear.pap) == ("green", "green")


async def test_async_upsert_same_rules(async_db_session: AsyncSession) -> None:
    repo = AsyncIndicatorRepo(async_db_session)
    kw = {"source_url": "https://s/1", "source_name": "s"}
    ind = await repo.upsert(type="ip", value="198.51.100.5", tlp="amber", **kw)
    ind.valid_until = _now() - 10 * _DAY
    await repo.upsert(type="ip", value="198.51.100.5", **kw)
    assert ind.state == "active"
    assert abs(ind.valid_until - (_now() + 30 * _DAY)) < _SLOP
    assert ind.tlp == "amber"
