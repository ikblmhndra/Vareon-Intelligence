"""Resolver entitas (Python) dan kembaran SQL `entity_resolve()` pada Postgres NYATA."""

from __future__ import annotations

import threading

from cti_core.db.engine import get_sync_engine
from cti_core.db.models.entity import Entity, EntityAlias
from cti_core.entity.resolve import resolve, resolve_async
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


def _make(s: Session, type_: str, name: str, *aliases: str) -> Entity:
    e = Entity(type=type_, stix_id=f"{type_}--{name}", name=name, source="analyst")
    s.add(e)
    s.flush()
    for a in (name, *aliases):
        s.add(
            EntityAlias(
                entity_id=e.id,
                entity_type=type_,
                alias=a,
                alias_norm=" ".join(a.lower().split()),
                source="analyst",
            )
        )
    s.flush()
    return e


def test_resolve_by_alias_case_and_space(db_session: Session) -> None:
    e = _make(db_session, "intrusion-set", "APT29", "apt 29")
    got = resolve(db_session, "intrusion-set", "  APT   29 ", source="dictionary")
    assert got.id == e.id


def test_resolve_creates_once(db_session: Session) -> None:
    a = resolve(db_session, "malware", "Brand  New", source="dictionary")
    b = resolve(db_session, "malware", "brand new", source="galaxy")
    assert a.id == b.id and a.name == "Brand New"
    n = db_session.scalar(select(func.count()).select_from(Entity).where(Entity.id == a.id))
    aliases = db_session.execute(select(EntityAlias).where(EntityAlias.entity_id == a.id)).scalars()
    rows = list(aliases)
    assert n == 1 and len(rows) == 1
    assert rows[0].source == "dictionary" and rows[0].alias_norm == "brand new"


def test_resolve_follows_merge(db_session: Session) -> None:
    old = _make(db_session, "intrusion-set", "Old Name")
    live = _make(db_session, "intrusion-set", "Live Name")
    old.merged_into_id = live.id
    db_session.flush()
    assert resolve(db_session, "intrusion-set", "old name", source="dictionary").id == live.id


def test_resolve_same_name_other_type_is_separate(db_session: Session) -> None:
    a = resolve(db_session, "malware", "Cobalt", source="dictionary")
    b = resolve(db_session, "tool", "Cobalt", source="dictionary")
    assert a.id != b.id


def test_resolve_returns_suppressed(db_session: Session) -> None:
    e = _make(db_session, "malware", "Noise")
    e.suppressed = True
    db_session.flush()
    got = resolve(db_session, "malware", "noise", source="dictionary")
    assert got.id == e.id and got.suppressed


def test_resolve_concurrent(db_session: Session) -> None:
    engine = get_sync_engine()
    barrier = threading.Barrier(2)
    ids: list[int] = []

    def worker() -> None:
        with Session(engine) as s:
            barrier.wait()
            ids.append(resolve(s, "intrusion-set", "NewActor", source="dictionary").id)
            s.commit()

    try:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(ids) == 2 and ids[0] == ids[1]
        with Session(engine) as s:
            assert (
                s.scalar(select(func.count()).select_from(Entity).where(Entity.name == "NewActor"))
                == 1
            )
    finally:
        with Session(engine) as s:
            s.execute(delete(Entity).where(Entity.name == "NewActor"))
            s.commit()


async def test_resolve_async(async_db_session: AsyncSession) -> None:
    a = await resolve_async(async_db_session, "tool", "Async  Tool", source="analyst")
    b = await resolve_async(async_db_session, "tool", "async tool", source="analyst")
    assert a.id == b.id and a.name == "Async Tool"


def test_sql_twin_agrees(db_session: Session) -> None:
    live = _make(db_session, "intrusion-set", "Live Group", "lg alias")
    gone = _make(db_session, "intrusion-set", "Gone Group")
    gone.merged_into_id = live.id
    _make(db_session, "malware", "Emotet")
    db_session.flush()
    cases = [
        ("intrusion-set", "Live Group"),
        ("intrusion-set", "  live   GROUP "),
        ("intrusion-set", "LG Alias"),
        ("intrusion-set", "gone group"),  # merged
        ("malware", "EMOTET"),
        ("tool", "Emotet"),  # tipe lain: terpisah
        ("malware", "Fresh One"),  # baru
        ("malware", "fresh   one"),
        ("tool", "Tab\tSeparated"),
        ("identity", "Ünï Çode"),
        ("campaign", "  Spaced  "),
        ("location", "ID"),
    ]
    for type_, name in cases:
        py = resolve(db_session, type_, name, source="dictionary").id
        sql = db_session.execute(
            text("SELECT entity_resolve(:t, :n, 'dictionary')"), {"t": type_, "n": name}
        ).scalar_one()
        assert sql == py, (type_, name)
    # urutan terbalik: SQL membuat dulu, Python harus menemukan entitas yang sama
    sql_first = db_session.execute(
        text("SELECT entity_resolve('tool', 'Sql First', 'dictionary')")
    ).scalar_one()
    assert resolve(db_session, "tool", "sql  FIRST", source="dictionary").id == sql_first
