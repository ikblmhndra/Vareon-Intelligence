"""Trigger jam feed P7c-1 (spec 3.5) pada Postgres NYATA, pola `test_machine_api_migration.py`.

Di dalam satu transaksi test `now()` konstan, jadi tiap test memundurkan `feed_changed_at` ke
2020-01-01 lewat UPDATE polos (tak ada kolom terpantau yang berubah, trigger membiarkan nilai yang
di-assign), lalu mengubah field dan menegaskan `>= now()` (trigger memakai `clock_timestamp()`)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from cti_core.db.models.article import Article
from sqlalchemy import text
from sqlalchemy.orm import Session

_OLD = "2020-01-01T00:00:00Z"


def _age(s: Session, table: str, row_id: int) -> None:
    s.execute(
        text(f"UPDATE {table} SET feed_changed_at = :t WHERE id = :i"), {"t": _OLD, "i": row_id}
    )


def _bumped(s: Session, table: str, row_id: int) -> bool:
    return s.execute(
        text(f"SELECT feed_changed_at >= now() FROM {table} WHERE id = :i"), {"i": row_id}
    ).scalar_one()


def _entity(s: Session, type_: str, name: str) -> int:
    return s.execute(
        text(
            "INSERT INTO entities (type, stix_id, name, source) VALUES (:t, :s, :n, 'analyst')"
            " RETURNING id"
        ),
        {"t": type_, "s": f"{type_}--{name}", "n": name},
    ).scalar_one()


@pytest.fixture
def ent(db_session: Session) -> Iterator[tuple[Session, int]]:
    eid = _entity(db_session, "intrusion-set", "feed-actor")
    _age(db_session, "entities", eid)
    assert not _bumped(db_session, "entities", eid)
    yield db_session, eid


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("name", "'renamed'"),
        ("description", "'baru'"),
        ("external_id", "'G9999'"),
        ("suppressed", "true"),
        ("merged_into_id", "(SELECT id FROM entities WHERE name = 'feed-target')"),
        ("tlp", "'amber'"),
        ("identity_class", "'class'"),
    ],
)
def test_entity_bumps_on_feed_fields(ent: tuple[Session, int], column: str, value: str) -> None:
    s, eid = ent
    _entity(s, "intrusion-set", "feed-target")
    s.execute(text(f"UPDATE entities SET {column} = {value} WHERE id = :i"), {"i": eid})
    assert _bumped(s, "entities", eid)


def test_last_seen_does_not_bump(ent: tuple[Session, int]) -> None:
    s, eid = ent
    s.execute(
        text("UPDATE entities SET first_seen = now(), last_seen = now() WHERE id = :i"), {"i": eid}
    )
    assert not _bumped(s, "entities", eid)


def test_updated_at_only_does_not_bump(ent: tuple[Session, int]) -> None:
    s, eid = ent
    s.execute(text("UPDATE entities SET updated_at = now() WHERE id = :i"), {"i": eid})
    assert not _bumped(s, "entities", eid)


def test_alias_insert_and_delete_bump_entity(ent: tuple[Session, int]) -> None:
    s, eid = ent
    s.execute(
        text(
            "INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)"
            " VALUES (:e, 'intrusion-set', 'Foo', 'foo', 'analyst')"
        ),
        {"e": eid},
    )
    assert _bumped(s, "entities", eid)
    _age(s, "entities", eid)
    s.execute(text("DELETE FROM entity_aliases WHERE entity_id = :e"), {"e": eid})
    assert _bumped(s, "entities", eid)


@pytest.mark.parametrize("assignment", ["entity_id = :other", "alias = 'Foo2'"])
def test_alias_update_bumps_old_and_new_entity(ent: tuple[Session, int], assignment: str) -> None:
    """Merge/split memindah alias lewat UPDATE (Ruling 14): entitas lama dan baru sama-sama bump."""
    s, eid = ent
    other = _entity(s, "intrusion-set", "feed-other")
    s.execute(
        text(
            "INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)"
            " VALUES (:e, 'intrusion-set', 'Foo', 'foo', 'analyst')"
        ),
        {"e": eid},
    )
    _age(s, "entities", eid)
    _age(s, "entities", other)
    s.execute(
        text(f"UPDATE entity_aliases SET {assignment} WHERE entity_id = :e"),
        {"e": eid, "other": other},
    )
    assert _bumped(s, "entities", eid)
    assert _bumped(s, "entities", other) == assignment.startswith("entity_id")


@pytest.fixture
def rel(db_session: Session) -> Iterator[tuple[Session, int]]:
    a = _entity(db_session, "intrusion-set", "rel-a")
    b = _entity(db_session, "malware", "rel-b")
    _entity(db_session, "tool", "rel-c")  # ujung pengganti untuk test ganti sumber/target
    rid = db_session.execute(
        text(
            "INSERT INTO relationships (stix_id, relationship_type, source_entity_id,"
            " target_entity_id, confidence, provenance) VALUES ('relationship--x', 'uses',"
            " :a, :b, 75, 'analyst') RETURNING id"
        ),
        {"a": a, "b": b},
    ).scalar_one()
    _age(db_session, "relationships", rid)
    assert not _bumped(db_session, "relationships", rid)
    yield db_session, rid


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("relationship_type", "'targets'"),
        ("source_entity_id", "(SELECT id FROM entities WHERE name = 'rel-c')"),
        ("target_entity_id", "(SELECT id FROM entities WHERE name = 'rel-c')"),
        ("confidence", "90"),
        ("description", "'x'"),
        ("revoked_at", "now()"),
        ("tlp", "'red'"),
    ],
)
def test_relationship_bumps_on_feed_fields(
    rel: tuple[Session, int], column: str, value: str
) -> None:
    s, rid = rel
    s.execute(text(f"UPDATE relationships SET {column} = {value} WHERE id = :i"), {"i": rid})
    assert _bumped(s, "relationships", rid)


def test_relationship_source_indicator_bumps(rel: tuple[Session, int]) -> None:
    s, rid = rel
    ind = s.execute(
        text(
            "INSERT INTO indicators (type, value, seen_count, tp_count, fp_count, auto_suppressed,"
            " enrichment, confidence_score) VALUES ('domain', 'rel.example', 1, 0, 0, false,"
            " '{}', 50) RETURNING id"
        )
    ).scalar_one()
    s.execute(
        text(
            "UPDATE relationships SET source_entity_id = NULL, source_indicator_id = :n"
            " WHERE id = :i"
        ),
        {"n": ind, "i": rid},
    )
    assert _bumped(s, "relationships", rid)


def test_relationship_confidence_bumps(rel: tuple[Session, int]) -> None:
    s, rid = rel
    s.execute(text("UPDATE relationships SET confidence = 10 WHERE id = :i"), {"i": rid})
    assert _bumped(s, "relationships", rid)


@pytest.mark.parametrize(
    "assignment", ["last_seen = now()", "first_seen = now()", "updated_at = now()"]
)
def test_relationship_ignores_seen_and_updated_at(
    rel: tuple[Session, int], assignment: str
) -> None:
    s, rid = rel
    s.execute(text(f"UPDATE relationships SET {assignment} WHERE id = :i"), {"i": rid})
    assert not _bumped(s, "relationships", rid)


@pytest.fixture
def story(db_session: Session) -> Iterator[tuple[Session, dict[str, Any]]]:
    s = db_session
    sid = s.execute(
        text("INSERT INTO stories (title, lead_source) VALUES ('t', 'src') RETURNING id")
    ).scalar_one()
    arts = [
        Article(url="http://x/1", url_hash="h1", title="a", source="src", story_id=sid),
        Article(url="http://x/2", url_hash="h2", title="b", source="src"),
    ]
    s.add_all(arts)
    s.flush()
    aid, orphan = arts[0].id, arts[1].id
    eid = _entity(s, "malware", "feed-mal")
    _age(s, "stories", sid)
    assert not _bumped(s, "stories", sid)
    yield s, {"sid": sid, "aid": aid, "orphan": orphan, "eid": eid}


@pytest.mark.parametrize(("column", "value"), [("title", "'t2'"), ("article_count", "5")])
def test_story_bumps_on_feed_fields(
    story: tuple[Session, dict[str, Any]], column: str, value: str
) -> None:
    s, ids = story
    s.execute(text(f"UPDATE stories SET {column} = {value} WHERE id = :i"), {"i": ids["sid"]})
    assert _bumped(s, "stories", ids["sid"])


def test_story_last_seen_does_not_bump(story: tuple[Session, dict[str, Any]]) -> None:
    s, ids = story
    s.execute(text("UPDATE stories SET last_seen_at = now() WHERE id = :i"), {"i": ids["sid"]})
    assert not _bumped(s, "stories", ids["sid"])


def test_mention_insert_and_delete_bump_story(story: tuple[Session, dict[str, Any]]) -> None:
    s, ids = story
    mid = s.execute(
        text(
            "INSERT INTO entity_mentions (article_id, entity_id, method, matched_alias)"
            " VALUES (:a, :e, 'analyst', 'x') RETURNING id"
        ),
        {"a": ids["aid"], "e": ids["eid"]},
    ).scalar_one()
    assert _bumped(s, "stories", ids["sid"])
    _age(s, "stories", ids["sid"])
    s.execute(text("DELETE FROM entity_mentions WHERE id = :i"), {"i": mid})
    assert _bumped(s, "stories", ids["sid"])


def test_mention_without_story_or_article_is_harmless(
    story: tuple[Session, dict[str, Any]],
) -> None:
    s, ids = story
    s.execute(
        text(
            "INSERT INTO entity_mentions (article_id, entity_id, method, matched_alias)"
            " VALUES (:a, :e, 'analyst', 'x')"
        ),
        {"a": ids["orphan"], "e": ids["eid"]},
    )
    ind = s.execute(
        text(
            "INSERT INTO indicators (type, value, seen_count, tp_count, fp_count, auto_suppressed,"
            " enrichment, confidence_score) VALUES ('domain', 'm.example', 1, 0, 0, false,"
            " '{}', 50) RETURNING id"
        )
    ).scalar_one()
    s.execute(
        text(
            "INSERT INTO entity_mentions (indicator_id, entity_id, method, matched_alias)"
            " VALUES (:n, :e, 'analyst', 'x')"
        ),
        {"n": ind, "e": ids["eid"]},
    )
    assert not _bumped(s, "stories", ids["sid"])


def test_mention_update_bumps_old_and_new_story(story: tuple[Session, dict[str, Any]]) -> None:
    """Merge/split memindah mention lewat UPDATE (Ruling 14): story lama dan baru sama-sama bump."""
    s, ids = story
    sid2 = s.execute(
        text("INSERT INTO stories (title, lead_source) VALUES ('t2', 'src') RETURNING id")
    ).scalar_one()
    s.execute(
        text("UPDATE articles SET story_id = :s WHERE id = :a"), {"s": sid2, "a": ids["orphan"]}
    )
    mid = s.execute(
        text(
            "INSERT INTO entity_mentions (article_id, entity_id, method, matched_alias)"
            " VALUES (:a, :e, 'analyst', 'x') RETURNING id"
        ),
        {"a": ids["aid"], "e": ids["eid"]},
    ).scalar_one()
    _age(s, "stories", ids["sid"])
    _age(s, "stories", sid2)
    s.execute(
        text("UPDATE entity_mentions SET article_id = :a WHERE id = :i"),
        {"a": ids["orphan"], "i": mid},
    )
    assert _bumped(s, "stories", ids["sid"]) and _bumped(s, "stories", sid2)

    other = _entity(s, "malware", "feed-mal-2")
    _age(s, "stories", sid2)
    s.execute(
        text("UPDATE entity_mentions SET entity_id = :e WHERE id = :i"), {"e": other, "i": mid}
    )
    assert _bumped(s, "stories", sid2)


# ── Propagasi jam (Ruling 33, spec R7) ─────────────────────────────────────


@pytest.fixture
def graph(db_session: Session) -> Iterator[tuple[Session, dict[str, int]]]:
    """Entitas `g-a` jadi sumber satu relasi dan target relasi lain, disebut artikel story `sid`;
    relasi `other` dan story `sid2` tidak menyentuhnya."""
    s = db_session
    a = _entity(s, "intrusion-set", "g-a")
    b = _entity(s, "malware", "g-b")
    c = _entity(s, "tool", "g-c")
    rels = {}
    for name, src, dst in (("as_src", a, b), ("as_dst", c, a), ("other", c, b)):
        rels[name] = s.execute(
            text(
                "INSERT INTO relationships (stix_id, relationship_type, source_entity_id,"
                " target_entity_id, provenance) VALUES (:x, 'uses', :s, :d, 'analyst')"
                " RETURNING id"
            ),
            {"x": f"relationship--{name}", "s": src, "d": dst},
        ).scalar_one()
    sid, sid2 = (
        s.execute(
            text("INSERT INTO stories (title, lead_source) VALUES (:t, 'src') RETURNING id"),
            {"t": t},
        ).scalar_one()
        for t in ("g1", "g2")
    )
    arts = [
        Article(url="http://g/1", url_hash="g1", title="a", source="src", story_id=sid),
        Article(url="http://g/2", url_hash="g2", title="b", source="src", story_id=sid2),
    ]
    s.add_all(arts)
    s.flush()
    for art, ent in ((arts[0], a), (arts[1], b)):
        s.execute(
            text(
                "INSERT INTO entity_mentions (article_id, entity_id, method, matched_alias)"
                " VALUES (:a, :e, 'analyst', 'x')"
            ),
            {"a": art.id, "e": ent},
        )
    ids = {"a": a, "b": b, "sid": sid, "sid2": sid2, "aid": arts[0].id, **rels}
    for rid in rels.values():
        _age(s, "relationships", rid)
    _age(s, "stories", sid)
    _age(s, "stories", sid2)
    yield s, ids


@pytest.mark.parametrize(
    "assignment",
    [
        "suppressed = true",
        "tlp = 'amber'",
        "merged_into_id = (SELECT id FROM entities WHERE name = 'g-b')",
    ],
)
def test_entity_visibility_change_bumps_relationships_and_stories(
    graph: tuple[Session, dict[str, int]], assignment: str
) -> None:
    s, ids = graph
    s.execute(text(f"UPDATE entities SET {assignment} WHERE id = :i"), {"i": ids["a"]})
    assert _bumped(s, "relationships", ids["as_src"])
    assert _bumped(s, "relationships", ids["as_dst"])
    assert _bumped(s, "stories", ids["sid"])
    assert not _bumped(s, "relationships", ids["other"])
    assert not _bumped(s, "stories", ids["sid2"])


@pytest.mark.parametrize("assignment", ["name = 'g-a2'", "description = 'x'", "tlp = 'clear'"])
def test_entity_other_change_does_not_propagate(
    graph: tuple[Session, dict[str, int]], assignment: str
) -> None:
    s, ids = graph
    s.execute(text(f"UPDATE entities SET {assignment} WHERE id = :i"), {"i": ids["a"]})
    assert not _bumped(s, "relationships", ids["as_src"])
    assert not _bumped(s, "stories", ids["sid"])


def test_indicator_source_insert_and_delete_bump_story(
    graph: tuple[Session, dict[str, int]],
) -> None:
    s, ids = graph
    ind = s.execute(
        text(
            "INSERT INTO indicators (type, value, seen_count, tp_count, fp_count, auto_suppressed,"
            " enrichment, confidence_score) VALUES ('domain', 'src.example', 1, 0, 0, false,"
            " '{}', 50) RETURNING id"
        )
    ).scalar_one()
    src = s.execute(
        text(
            "INSERT INTO indicator_sources (indicator_id, article_id, url, source_name)"
            " VALUES (:n, :a, 'http://g/1', 'src') RETURNING id"
        ),
        {"n": ind, "a": ids["aid"]},
    ).scalar_one()
    assert _bumped(s, "stories", ids["sid"])
    assert not _bumped(s, "stories", ids["sid2"])
    _age(s, "stories", ids["sid"])
    s.execute(text("DELETE FROM indicator_sources WHERE id = :i"), {"i": src})
    assert _bumped(s, "stories", ids["sid"])


def test_indicator_source_move_bumps_old_and_new_story(
    graph: tuple[Session, dict[str, int]],
) -> None:
    s, ids = graph
    ind = s.execute(
        text(
            "INSERT INTO indicators (type, value, seen_count, tp_count, fp_count, auto_suppressed,"
            " enrichment, confidence_score) VALUES ('domain', 'mv.example', 1, 0, 0, false,"
            " '{}', 50) RETURNING id"
        )
    ).scalar_one()
    # dua baris dalam satu statement: trigger level statement, story tetap ter-bump
    s.execute(
        text(
            "INSERT INTO indicator_sources (indicator_id, article_id, url, source_name)"
            " VALUES (:n, :a, 'http://g/1', 'src'), (:n, :a, 'http://g/1b', 'src')"
        ),
        {"n": ind, "a": ids["aid"]},
    )
    _age(s, "stories", ids["sid"])
    s.execute(
        text("UPDATE indicator_sources SET context = 'x' WHERE indicator_id = :n"), {"n": ind}
    )
    assert not _bumped(s, "stories", ids["sid"])  # article_id tidak berubah
    aid2 = s.execute(
        text("SELECT id FROM articles WHERE story_id = :s"), {"s": ids["sid2"]}
    ).scalar_one()
    s.execute(
        text("UPDATE indicator_sources SET article_id = :a WHERE indicator_id = :n"),
        {"a": aid2, "n": ind},
    )
    assert _bumped(s, "stories", ids["sid"]) and _bumped(s, "stories", ids["sid2"])
