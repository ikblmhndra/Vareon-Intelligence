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
