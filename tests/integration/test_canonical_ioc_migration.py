"""Migrasi 0.8.6 (`e7b2d4a9c6f1`): IOC lama ke bentuk kanonik + merge kembaran, kanonik
`threat_feed_entries`, seed allowlist, dan penandaan IOC yang cocok allowlist -- Postgres REAL."""

from __future__ import annotations

import datetime
import importlib.util
import pathlib
from types import ModuleType
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"
_D0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
_D1 = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)
_D2 = datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC)


def _load_migration() -> ModuleType:
    path = next(_VERSIONS.glob("e7b2d4a9c6f1_*.py"))
    spec = importlib.util.spec_from_file_location("canonical_iocs_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def _ioc(session: Session, ioc_type: str, value: str, **cols: Any) -> int:
    row = {
        "seen_count": 1,
        "tp_count": 0,
        "fp_count": 0,
        "first_seen_at": _D1,
        "last_seen_at": _D1,
        "enrichment": "{}",
        "auto_suppressed": False,
        "suppression_reason": None,
    } | cols
    return int(
        session.execute(
            text(
                "INSERT INTO iocs (type, value, seen_count, tp_count, fp_count, first_seen_at,"
                " last_seen_at, enrichment, auto_suppressed, suppression_reason, confidence_score)"
                " VALUES (:type, :value, :seen_count, :tp_count, :fp_count, :first_seen_at,"
                " :last_seen_at, CAST(:enrichment AS jsonb), :auto_suppressed,"
                " :suppression_reason, 50) RETURNING id"
            ),
            {"type": ioc_type, "value": value, **row},
        ).scalar_one()
    )


def _source(session: Session, ioc_id: int, url: str) -> None:
    session.execute(
        text("INSERT INTO ioc_sources (ioc_id, url, source_name) VALUES (:i, :u, 's')"),
        {"i": ioc_id, "u": url},
    )


def _iocs(session: Session, ioc_type: str) -> list[Any]:
    return list(
        session.execute(
            text("SELECT * FROM iocs WHERE type = :t ORDER BY id"), {"t": ioc_type}
        ).mappings()
    )


def _count(session: Session, sql: str, **params: Any) -> int:
    return int(session.execute(text(sql), params).scalar_one())


def test_merge_defanged_twin(db_session: Session) -> None:
    twin = _ioc(
        db_session,
        "domain",
        "evil[.]com",
        seen_count=2,
        tp_count=1,
        first_seen_at=_D1,
        last_seen_at=_D1,
    )
    plain = _ioc(
        db_session,
        "domain",
        "evil.com",
        seen_count=3,
        fp_count=1,
        first_seen_at=_D0,
        last_seen_at=_D2,
        enrichment='{"otx": {"pulses": 2}}',
        auto_suppressed=True,
        suppression_reason="fp-feedback",
    )
    _source(db_session, twin, "https://a.example/1")
    _source(db_session, plain, "https://a.example/2")

    counts = migration.canonicalize_and_merge(db_session.connection())

    assert counts == {"merged": 1, "rewritten": 1}
    [row] = _iocs(db_session, "domain")
    assert row["id"] == twin == min(twin, plain)
    assert row["value"] == "evil.com"
    assert (row["seen_count"], row["tp_count"], row["fp_count"]) == (5, 1, 1)
    assert (row["first_seen_at"], row["last_seen_at"]) == (_D0, _D2)
    # enrichment penyintas kosong -> ambil yang pertama tidak kosong; suppression ikut terbawa
    assert row["enrichment"] == {"otx": {"pulses": 2}}
    assert (row["auto_suppressed"], row["suppression_reason"]) == (True, "fp-feedback")
    assert _count(db_session, "SELECT count(*) FROM ioc_sources WHERE ioc_id = :i", i=twin) == 2


def test_merge_skips_colliding_links(db_session: Session) -> None:
    ids = [_ioc(db_session, "domain", v, fp_count=1) for v in ("bad[.]org", "bad.org")]
    for ioc_id in ids:
        db_session.execute(
            text("INSERT INTO ioc_tags (ioc_id, tag) VALUES (:i, 'phishing')"), {"i": ioc_id}
        )
        db_session.execute(
            text("INSERT INTO ioc_threat_actors (ioc_id, threat_actor) VALUES (:i, 'APT1')"),
            {"i": ioc_id},
        )
        db_session.execute(
            text(
                "INSERT INTO ioc_feedback (ioc_id, verdict, submitted_by)"
                " VALUES (:i, 'fp', 'alice')"
            ),
            {"i": ioc_id},
        )
    # tag/feedback yang hanya ada di kembaran ikut pindah
    db_session.execute(text("INSERT INTO ioc_tags (ioc_id, tag) VALUES (:i, 'c2')"), {"i": ids[1]})
    db_session.execute(
        text("INSERT INTO ioc_feedback (ioc_id, verdict, submitted_by) VALUES (:i, 'tp', 'bob')"),
        {"i": ids[1]},
    )

    migration.canonicalize_and_merge(db_session.connection())

    [row] = _iocs(db_session, "domain")
    survivor = row["id"]
    assert survivor == ids[0]
    tags = db_session.execute(
        text("SELECT tag FROM ioc_tags WHERE ioc_id = :i ORDER BY tag"), {"i": survivor}
    ).scalars()
    assert list(tags) == ["c2", "phishing"]
    assert _count(db_session, "SELECT count(*) FROM ioc_threat_actors") == 1
    feedback = db_session.execute(
        text("SELECT verdict, submitted_by FROM ioc_feedback WHERE ioc_id = :i ORDER BY verdict"),
        {"i": survivor},
    ).all()
    assert [tuple(f) for f in feedback] == [("fp", "alice"), ("tp", "bob")]
    assert _count(db_session, "SELECT count(*) FROM ioc_feedback") == 2
    # kolom hitungan dijumlah apa adanya (spec 3.3), tiap baris dihitung sekali
    assert row["fp_count"] == 2


def test_case_duplicates_merge(db_session: Session) -> None:
    _ioc(db_session, "sha256", "ABC")
    _ioc(db_session, "sha256", "abc")

    migration.canonicalize_and_merge(db_session.connection())

    assert [r["value"] for r in _iocs(db_session, "sha256")] == ["abc"]


def test_url_path_case_kept(db_session: Session) -> None:
    _ioc(db_session, "url", "hxxps://A[.]com/X")

    counts = migration.canonicalize_and_merge(db_session.connection())

    assert counts == {"merged": 0, "rewritten": 1}
    assert [r["value"] for r in _iocs(db_session, "url")] == ["https://a.com/X"]


def test_three_way_merge_chain(db_session: Session) -> None:
    # tiga bentuk satu indikator; nilai kanonik dipegang baris id TERBESAR (bukan penyintas)
    ids = [_ioc(db_session, "domain", v) for v in ("Evil[.]NET", "evil[dot]net", "evil.net")]
    _ioc(db_session, "domain", "other.net")

    counts = migration.canonicalize_and_merge(db_session.connection())

    assert counts == {"merged": 2, "rewritten": 1}
    rows = _iocs(db_session, "domain")
    assert [(r["id"], r["value"], r["seen_count"]) for r in rows][:1] == [(ids[0], "evil.net", 3)]
    assert [r["value"] for r in rows] == ["evil.net", "other.net"]


def test_threat_feed_entries_canonicalized(db_session: Session) -> None:
    for feed, t, v in [
        ("deepdarkcti_c2", "domain", "C2[.]Example"),
        ("deepdarkcti_c2", "domain", "c2.example"),
        ("deepdarkcti_c2", "ip", "5[.]6[.]7[.]8"),
        ("other_feed", "domain", "c2.example"),
    ]:
        db_session.execute(
            text("INSERT INTO threat_feed_entries (feed, type, value) VALUES (:f, :t, :v)"),
            {"f": feed, "t": t, "v": v},
        )

    counts = migration.canonicalize_threat_feed(db_session.connection())

    assert counts == {"merged": 1, "rewritten": 2}  # penyintas C2[.]Example + IP
    rows = db_session.execute(
        text("SELECT feed, type, value FROM threat_feed_entries ORDER BY feed, type, value")
    ).all()
    assert [tuple(r) for r in rows] == [
        ("deepdarkcti_c2", "domain", "c2.example"),
        ("deepdarkcti_c2", "ip", "5.6.7.8"),
        ("other_feed", "domain", "c2.example"),
    ]


def test_seed_and_flag(db_session: Session) -> None:
    conn = db_session.connection()
    # Skema test sudah di-upgrade ke head, jadi seed sudah ada; kosongkan dulu untuk menguji
    # penyisipan, plus satu entri analis yang juga harus menandai.
    conn.execute(text("DELETE FROM ioc_allowlist_entries"))
    conn.execute(
        text(
            "INSERT INTO ioc_allowlist_entries (type, value, added_by)"
            " VALUES ('ip', '9.9.9.9', 'analyst'), ('email_domain', 'corp.example', 'analyst')"
        )
    )
    gofile = _ioc(db_session, "domain", "store1.gofile.io")
    payload = _ioc(db_session, "url", "https://gofile.io/d/abc123")
    ip = _ioc(db_session, "ip", "9.9.9.9")
    email = _ioc(db_session, "email", "bob@mail.corp.example")
    clean = _ioc(db_session, "domain", "notgofile.io")
    kept = _ioc(db_session, "domain", "github.com", auto_suppressed=True, suppression_reason="x")

    first = migration.seed_and_flag_allowlist(conn)

    assert first == {"seeded": len(migration.SEED_URL_DOMAINS), "flagged": 3}
    reasons = dict(
        db_session.execute(text("SELECT id, suppression_reason FROM iocs WHERE auto_suppressed"))
        .tuples()
        .all()
    )
    assert reasons == {
        gofile: "allowlist:url_domain:gofile.io (infrastructure-abuse)",
        ip: "allowlist:ip:9.9.9.9 (infrastructure-abuse)",
        email: "allowlist:email_domain:corp.example (infrastructure-abuse)",
        kept: "x",  # alasan yang sudah ada tidak ditimpa
    }
    assert payload not in reasons and clean not in reasons
    assert (
        _count(
            db_session,
            "SELECT count(*) FROM ioc_allowlist_entries"
            " WHERE type = 'url_domain' AND value = 'gofile.io' AND added_by = 'seed'",
        )
        == 1
    )

    assert migration.seed_and_flag_allowlist(conn) == {"seeded": 0, "flagged": 0}
