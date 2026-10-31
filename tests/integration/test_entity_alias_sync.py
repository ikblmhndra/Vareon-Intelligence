"""`sync_galaxy` (spec 4.3) pada Postgres NYATA: validasi, shrink guard 20 %, salinan lama
dipertahankan per file, merge hanya bila ada salinan."""

from __future__ import annotations

from typing import Any

import pytest
from cti_core.db.models.entity import Entity, EntityAlias, ReferenceSnapshot
from cti_core.entity import alias_norm
from cti_core.entity.galaxy import GALAXY_FILES, snapshot_name
from sqlalchemy import select
from sqlalchemy.orm import Session

IS = "intrusion-set"


def galaxy_url(name: str) -> str:
    from cti_worker.tasks.entity import galaxy_url as f

    return f(name)


def sync_galaxy(session: Session, fetch: Any) -> Any:
    from cti_worker.tasks.entity import sync_galaxy as f

    return f(session, fetch)


def _content(n: int, *, extra: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    vals = [{"uuid": f"u{i}", "value": f"Cluster{i}"} for i in range(n)]
    return {"values": vals + (extra or [])}


def _store(s: Session, name: str, content: dict[str, Any]) -> None:
    s.merge(ReferenceSnapshot(name=snapshot_name(name), sha256="0" * 64, content=content))
    s.flush()


def _prestore(s: Session, n: int = 5, **sizes: int) -> None:
    """Salinan tersimpan kecil untuk semua file, supaya shrink guard tidak membandingkan tes
    dengan snapshot bawaan paket (ribuan cluster)."""
    for name in GALAXY_FILES:
        _store(s, name, _content(sizes.get(name.replace("-", "_"), n)))


def _fetcher(files: dict[str, Any]):
    def fetch(url: str) -> dict[str, Any]:
        for name, body in files.items():
            if url == galaxy_url(name):
                if isinstance(body, Exception):
                    raise body
                return body
        raise AssertionError(url)

    return fetch


def _stored(s: Session, name: str) -> dict[str, Any] | None:
    row = s.get(ReferenceSnapshot, snapshot_name(name))
    return None if row is None else row.content


@pytest.fixture
def session(db_session: Session) -> Session:
    return db_session


def test_shrink_guard_rejects(session: Session) -> None:
    _prestore(session, malpedia=1000)
    ok = {n: _content(5) for n in GALAXY_FILES if n != "malpedia"}
    res = sync_galaxy(session, _fetcher({**ok, "malpedia": _content(790)}))
    assert "malpedia" in res.rejected and "malpedia" not in res.stored
    assert len(_stored(session, "malpedia")["values"]) == 1000  # type: ignore[index]
    assert sorted(res.stored) == ["ransomware", "threat-actor"]


def test_shrink_within_20_percent_accepted(session: Session) -> None:
    _prestore(session, malpedia=1000)
    ok = {n: _content(5) for n in GALAXY_FILES}
    ok["malpedia"] = _content(800)
    res = sync_galaxy(session, _fetcher(ok))
    assert "malpedia" in res.stored and not res.rejected


def test_bad_schema_rejected(session: Session) -> None:
    _prestore(session, 3)
    files: dict[str, Any] = {n: _content(3) for n in GALAXY_FILES}
    files["threat-actor"] = {"values": [{"uuid": "x"}]}
    files["ransomware"] = ["not", "an", "object"]
    res = sync_galaxy(session, _fetcher(files))
    assert set(res.rejected) == {"threat-actor", "ransomware"}
    assert res.stored == ["malpedia"]
    assert _stored(session, "threat-actor") == _content(3)  # salinan lama utuh


def test_http_error_keeps_previous(session: Session) -> None:
    prev = _content(10)
    _prestore(session, 3)
    _store(session, "ransomware", prev)
    files: dict[str, Any] = {n: _content(3) for n in GALAXY_FILES}
    files["ransomware"] = RuntimeError("boom")
    res = sync_galaxy(session, _fetcher(files))
    assert "boom" in res.rejected["ransomware"]
    assert _stored(session, "ransomware") == prev
    assert sorted(res.stored) == ["malpedia", "threat-actor"]


def test_all_rejected_without_stored_copy_skips_merge(session: Session) -> None:
    err = RuntimeError("down")
    res = sync_galaxy(session, _fetcher({n: err for n in GALAXY_FILES}))
    assert res.stored == [] and res.applied is None


def test_success_stores_and_applies(session: Session) -> None:
    def ent(name: str) -> Entity:
        e = Entity(type=IS, stix_id=f"{IS}--sync-{name}", name=name, source="dictionary")
        session.add(e)
        session.flush()
        session.add(
            EntityAlias(
                entity_id=e.id,
                entity_type=IS,
                alias=name,
                alias_norm=alias_norm(name),
                source="dictionary",
            )
        )
        return e

    _prestore(session, 1)
    a, b = ent("Sync Actor Alpha"), ent("Sync Actor Beta")
    session.flush()
    gal = {
        "values": [
            {"uuid": "g1", "value": "Sync Actor Alpha", "meta": {"synonyms": ["Sync Actor Beta"]}}
        ]
    }
    files = {"threat-actor": gal, "ransomware": _content(1), "malpedia": _content(1)}
    res = sync_galaxy(session, _fetcher(files))
    assert sorted(res.stored) == sorted(GALAXY_FILES) and not res.rejected
    assert res.applied is not None and res.applied.merged == 1
    assert _stored(session, "threat-actor") == gal
    live = session.scalars(
        select(Entity.id).where(Entity.id.in_([a.id, b.id]), Entity.merged_into_id.is_(None))
    ).all()
    assert len(live) == 1
