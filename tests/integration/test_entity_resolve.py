"""Resolver entitas (Python) dan kembaran SQL `entity_resolve()` pada Postgres NYATA."""

from __future__ import annotations

import threading

import pytest
from cti_core.db.engine import get_sync_engine
from cti_core.db.models.entity import Entity, EntityAlias
from cti_core.entity.resolve import resolve, resolve_async
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_UNICODE_WS = [0xA0, 0x1680, *range(0x2000, 0x200C), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF]


def _race(name: str, first: str, second: str) -> None:
    """Dua koneksi terpisah me-resolve `name` bersamaan (py/sql), commit, lalu bersihkan."""
    engine = get_sync_engine()
    barrier = threading.Barrier(2)
    ids: list[int] = []

    def worker(kind: str) -> None:
        with Session(engine) as s:
            barrier.wait()
            if kind == "py":
                ids.append(resolve(s, "intrusion-set", name, source="legacy").id)
            else:
                ids.append(
                    s.execute(
                        text("SELECT entity_resolve('intrusion-set', :n, 'legacy')"), {"n": name}
                    ).scalar_one()
                )
            s.commit()

    try:
        threads = [threading.Thread(target=worker, args=(k,)) for k in (first, second)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(ids) == 2 and ids[0] == ids[1]
        with Session(engine) as s:
            n = s.scalar(select(func.count()).select_from(Entity).where(Entity.name == name))
            assert n == 1
    finally:
        with Session(engine) as s:
            s.execute(delete(Entity).where(Entity.name == name))
            s.commit()


@pytest.mark.usefixtures("_migrated_schema")
def test_sql_concurrent() -> None:
    _race("NewActor2", "sql", "sql")


@pytest.mark.usefixtures("_migrated_schema")
def test_mixed_python_sql_concurrent() -> None:
    _race("NewActor3", "py", "sql")


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
        *[("campaign", f"Op{chr(cp)}  Name{chr(cp)}") for cp in _UNICODE_WS],
        ("campaign", "Op Name"),
        ("campaign", "Op\t\n\v\f\rName"),
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


# --- jalur teknik (Ruling 7): identitas attack-pattern = id teknik, bukan nama ---


def test_technique_requires_external_id(db_session: Session) -> None:
    with pytest.raises(ValueError):
        resolve(db_session, "attack-pattern", "Phishing", source="analyst")
    with pytest.raises(Exception, match="external_id"), db_session.begin_nested():
        db_session.execute(text("SELECT entity_resolve('attack-pattern', 'Phishing', 'legacy')"))


def test_technique_same_name_different_ids(db_session: Session) -> None:
    a = resolve(
        db_session, "attack-pattern", "Cloud Account", source="analyst", external_id="T1136.003"
    )
    b = resolve(
        db_session, "attack-pattern", "Cloud Account", source="analyst", external_id="T1087.004"
    )
    assert a.id != b.id and a.name == b.name == "Cloud Account"
    assert a.stix_id != b.stix_id
    again = resolve(
        db_session, "attack-pattern", "Other", source="analyst", external_id="t1136.003"
    )
    assert again.id == a.id and again.name == "Cloud Account"
    norms = db_session.scalars(
        select(EntityAlias.alias_norm).where(EntityAlias.entity_id == a.id)
    ).all()
    assert norms == ["t1136.003"]  # hanya id teknik, tanpa alias nama


async def test_technique_async(async_db_session: AsyncSession) -> None:
    a = await resolve_async(
        async_db_session, "attack-pattern", "X", source="analyst", external_id="T9001"
    )
    b = await resolve_async(
        async_db_session, "attack-pattern", "Y", source="analyst", external_id="T9001"
    )
    assert a.id == b.id and a.external_id == "T9001"
    with pytest.raises(ValueError):
        await resolve_async(async_db_session, "attack-pattern", "X", source="analyst")


def test_technique_sql_twin_agrees(db_session: Session) -> None:
    cases = [
        ("T1566.001", "Spearphishing Attachment"),
        ("T1598.002", "Spearphishing Attachment"),  # nama sama, id beda
        ("  t1566.001 ", "renamed"),
        ("T0809", "Data Destruction"),
    ]
    for ext, name in cases:
        py = resolve(db_session, "attack-pattern", name, source="legacy", external_id=ext).id
        sql = db_session.execute(
            text("SELECT entity_resolve_technique(:e, :n, 'legacy')"), {"e": ext, "n": name}
        ).scalar_one()
        assert sql == py, (ext, name)
    sql_first = db_session.execute(
        text("SELECT entity_resolve_technique('T1485', 'Data Destruction', 'legacy')")
    ).scalar_one()
    py = resolve(db_session, "attack-pattern", "x", source="legacy", external_id="t1485")
    assert py.id == sql_first and py.name == "Data Destruction"


def test_external_id_unique_per_type(db_session: Session) -> None:
    db_session.execute(
        text(
            "INSERT INTO entities (type, stix_id, name, source, external_id)"
            " VALUES ('vulnerability', 'v--1', 'CVE-1', 'cve', 'CVE-1')"
        )
    )
    with pytest.raises(Exception, match="uq_entities_type_external_id"), db_session.begin_nested():
        db_session.execute(
            text(
                "INSERT INTO entities (type, stix_id, name, source, external_id)"
                " VALUES ('vulnerability', 'v--2', 'CVE-1 dup', 'cve', 'CVE-1')"
            )
        )


def test_technique_id_uppercased(db_session: Session) -> None:
    existing = resolve(
        db_session,
        "attack-pattern",
        "Spearphishing Attachment",
        source="attack",
        external_id="T1566.001",
    )
    low = resolve(db_session, "attack-pattern", "x", source="legacy", external_id="t1566.001")
    assert low.id == existing.id
    py_new = resolve(db_session, "attack-pattern", "N", source="legacy", external_id=" t9002 ")
    sql_id = db_session.execute(
        text("SELECT entity_resolve_technique('t9003', 'M', 'legacy')")
    ).scalar_one()
    sql_new = db_session.scalar(select(Entity.external_id).where(Entity.id == sql_id))
    assert (py_new.external_id, sql_new) == ("T9002", "T9003")
    alias = db_session.scalar(select(EntityAlias.alias).where(EntityAlias.entity_id == py_new.id))
    assert alias == "T9002"


def test_resolve_after_merge_and_alias_removal(db_session: Session) -> None:
    """Merge A ke B lalu alias "foo" dihapus dari B: uuid5 "foo" sudah dipakai tombstone A,
    resolve harus membuat entitas baru dengan stix_id acak, bukan RuntimeError permanen."""
    from cti_core.entity.merge import merge_entities

    a = resolve(db_session, "intrusion-set", "Foo", source="dictionary")
    b = resolve(db_session, "intrusion-set", "Bar", source="dictionary")
    merge_entities(db_session, a.id, b.id, actor="t")
    db_session.execute(
        delete(EntityAlias).where(EntityAlias.entity_id == b.id, EntityAlias.alias_norm == "foo")
    )
    got = resolve(db_session, "intrusion-set", "foo", source="dictionary")
    assert got.id not in (a.id, b.id) and got.merged_into_id is None
    assert got.stix_id != a.stix_id and got.stix_id.startswith("intrusion-set--")


def test_resolve_after_rename_and_alias_removal(db_session: Session) -> None:
    e = resolve(db_session, "malware", "OldName", source="dictionary")
    e.name = "NewName"
    db_session.execute(delete(EntityAlias).where(EntityAlias.entity_id == e.id))
    db_session.flush()
    got = resolve(db_session, "malware", "oldname", source="dictionary")
    assert got.id != e.id and got.stix_id != e.stix_id


def test_named_cve_then_cve_mention(db_session: Session) -> None:
    """Analis membuat "Log4Shell" dengan external_id CVE; mention CVE menempel ke entitas itu."""
    from cti_core.entity.mentions import cve_mention, resolve_mention

    named = _make(db_session, "vulnerability", "Log4Shell")
    named.external_id = "CVE-2021-44228"
    db_session.flush()
    hit = cve_mention("cve-2021-44228", "explicit", in_title=False)
    assert hit is not None
    got = resolve_mention(db_session, hit)
    assert got is not None and got.id == named.id
    norms = db_session.scalars(
        select(EntityAlias.alias_norm).where(EntityAlias.entity_id == named.id)
    ).all()
    assert "cve-2021-44228" in norms


async def test_named_cve_then_cve_mention_async(async_db_session: AsyncSession) -> None:
    from cti_core.entity.mentions import cve_mention, resolve_mention_async

    s = async_db_session
    named = Entity(
        type="vulnerability",
        stix_id="vulnerability--log4shell-async",
        name="Log4Shell A",
        source="analyst",
        external_id="CVE-2021-45046",
    )
    s.add(named)
    await s.flush()
    hit = cve_mention("CVE-2021-45046", "explicit", in_title=False)
    assert hit is not None
    got = await resolve_mention_async(s, hit)
    assert got is not None and got.id == named.id
