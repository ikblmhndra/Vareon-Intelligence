"""Urutan kunci enrich vs suppress/merge (Ruling 36), dua koneksi NYATA dengan data ter-commit.

Enrich (A) memegang kunci story lebih dulu (`StoryRepo.attach`), lalu menulis mention dan
`touch_seen`. Suppress/merge (B) memegang entitas lalu, lewat `trg_entities_feed_propagate` atau
trigger mention, menunggu story yang sama. Test memastikan B BENAR-BENAR menunggu story (dicek di
`pg_stat_activity`) sebelum A lanjut, jadi interleaving deterministik. Sebelum Ruling 36 (merge
`FOR UPDATE`, touch_seen tanpa SKIP LOCKED) A menunggu entitas = deadlock. `lock_timeout` pendek
supaya regresi gagal cepat, bukan menggantung."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from cti_core.db.engine import get_sync_engine
from cti_core.entity.mentions import touch_seen
from cti_core.entity.merge import merge_entities, set_suppressed
from sqlalchemy import text
from sqlalchemy.orm import Session

_TAG = "lockorder"


def _setup(s: Session) -> dict[str, int]:
    ids: dict[str, int] = {}
    for key, name in (("e", f"{_TAG}-e"), ("f", f"{_TAG}-f")):
        ids[key] = s.execute(
            text(
                "INSERT INTO entities (type, stix_id, name, source) VALUES ('intrusion-set',"
                " :sid, :n, 'analyst') RETURNING id"
            ),
            {"sid": f"intrusion-set--{name}", "n": name},
        ).scalar_one()
    ids["story"] = s.execute(
        text("INSERT INTO stories (title, lead_source) VALUES (:t, 'src') RETURNING id"),
        {"t": _TAG},
    ).scalar_one()
    for key in ("a1", "a2"):
        ids[key] = s.execute(
            text(
                "INSERT INTO articles (url, url_hash, title, source, story_id, posted_on,"
                " raw_enrichment, overrides, confirmed_incident, c2_indicator, seen_count,"
                " schema_version) VALUES (:u, :h, 't', 'src', :s, '2026-10-01', '{}', '{}',"
                " false, false, 1, 1) RETURNING id"
            ),
            {"u": f"http://{_TAG}/{key}", "h": f"{_TAG}-{key}", "s": ids["story"]},
        ).scalar_one()
    # mention ter-commit: trigger propagate/mention B menyasar story ini
    s.execute(
        text(
            "INSERT INTO entity_mentions (article_id, entity_id, method, matched_alias)"
            " VALUES (:a, :e, 'analyst', 'x')"
        ),
        {"a": ids["a1"], "e": ids["e"]},
    )
    s.commit()
    return ids


def _cleanup(s: Session, ids: dict[str, int]) -> None:
    s.rollback()
    s.execute(text("DELETE FROM entity_mentions WHERE article_id IN (:a1, :a2)"), ids)
    s.execute(text("DELETE FROM articles WHERE id IN (:a1, :a2)"), ids)
    s.execute(text("DELETE FROM stories WHERE id = :story"), ids)
    s.execute(
        text("DELETE FROM audit_log WHERE target_id IN (:e, :f)"),
        {"e": str(ids["e"]), "f": str(ids["f"])},
    )
    s.execute(text("UPDATE entities SET merged_into_id = NULL WHERE id IN (:e, :f)"), ids)
    s.execute(text("DELETE FROM entities WHERE id IN (:e, :f)"), ids)
    s.commit()


@pytest.fixture
def committed(_migrated_schema: None) -> Iterator[tuple[Callable[[], Session], dict[str, int]]]:
    engine = get_sync_engine()

    def new_session() -> Session:
        s = Session(bind=engine)
        s.execute(text("SET lock_timeout = '5s'"))
        return s

    admin = Session(bind=engine)
    ids = _setup(admin)
    try:
        yield new_session, ids
    finally:
        _cleanup(admin, ids)
        admin.close()


def _wait_blocked(probe: Session, pid: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = probe.execute(
            text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :p"), {"p": pid}
        ).scalar_one_or_none()
        probe.rollback()
        if state == "Lock":
            return
        time.sleep(0.05)
    raise AssertionError("B tidak pernah menunggu kunci story")


@pytest.mark.parametrize("op", ["suppress", "merge"])
def test_enrich_and_entity_write_do_not_deadlock(
    committed: tuple[Callable[[], Session], dict[str, int]], op: str
) -> None:
    new_session, ids = committed
    a, b, probe = new_session(), new_session(), new_session()
    errors: list[BaseException] = []
    try:
        # A: kunci story dulu (padanan StoryRepo.attach)
        a.execute(
            text("UPDATE stories SET article_count = article_count + 1 WHERE id = :s"),
            {"s": ids["story"]},
        )
        b_pid = b.execute(text("SELECT pg_backend_pid()")).scalar_one()

        def run_b() -> None:
            try:
                if op == "suppress":
                    set_suppressed(b, ids["e"], True, actor="lock-test")
                else:
                    merge_entities(b, ids["e"], ids["f"], actor="lock-test")
                b.commit()
            except BaseException as exc:  # dicatat, dinilai di thread utama
                errors.append(exc)
                b.rollback()

        thread = threading.Thread(target=run_b)
        thread.start()
        _wait_blocked(probe, b_pid)  # B memegang entitas dan menunggu story A

        # A: mention untuk E (cek FK = KEY SHARE pada E) lalu touch_seen (NO KEY UPDATE)
        a.execute(
            text(
                "INSERT INTO entity_mentions (article_id, entity_id, method, matched_alias)"
                " VALUES (:a, :e, 'analyst', 'x')"
            ),
            {"a": ids["a2"], "e": ids["e"]},
        )
        touch_seen(a, ids["a2"])
        a.commit()
        thread.join(timeout=15)
        assert not thread.is_alive(), "B menggantung"
        assert not errors, errors
        row: Any = probe.execute(
            text("SELECT suppressed, merged_into_id FROM entities WHERE id = :e"), {"e": ids["e"]}
        ).one()
        assert row.suppressed if op == "suppress" else row.merged_into_id == ids["f"]
    finally:
        for s in (a, b, probe):
            s.rollback()
            s.close()
