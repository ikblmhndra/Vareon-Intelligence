"""Migrasi `entity_model` (P7c-1) pada Postgres NYATA: trigger tipe alias dan downgrade bersih."""

from __future__ import annotations

import datetime
import importlib.util
import pathlib
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cti_core.db.models.article import Article
from cti_core.db.models.attack import (
    AttackGroup,
    AttackRelationship,
    AttackSoftware,
    AttackTechnique,
)
from cti_core.db.models.auth import Client
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.indicator import Indicator
from cti_core.db.models.pir import PIRRequirement
from cti_core.db.models.ransomware import RansomwareVictim
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

_VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load_migration() -> ModuleType:
    path = next(_VERSIONS.glob("*_entity_model.py"))
    spec = importlib.util.spec_from_file_location("entity_model_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def _run(session: Session, fn: str) -> None:
    ctx = MigrationContext.configure(session.connection())
    with Operations.context(ctx):
        getattr(migration, fn)()


def _entity(session: Session, type_: str, name: str) -> int:
    return session.execute(
        text(
            "INSERT INTO entities (type, stix_id, name, source) VALUES (:t, :s, :n, 'analyst')"
            " RETURNING id"
        ),
        {"t": type_, "s": f"{type_}--{name}", "n": name},
    ).scalar_one()


def _alias(session: Session, entity_id: int, norm: str) -> None:
    # entity_type sengaja salah: trigger harus menimpanya.
    session.execute(
        text(
            "INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)"
            " VALUES (:e, 'bogus', :a, :a, 'analyst')"
        ),
        {"e": entity_id, "a": norm},
    )


def test_trigger_sets_alias_entity_type(db_session: Session) -> None:
    eid = _entity(db_session, "malware", "Emotet")
    _alias(db_session, eid, "emotet")
    got = db_session.execute(
        text("SELECT entity_type FROM entity_aliases WHERE entity_id = :e"), {"e": eid}
    ).scalar_one()
    assert got == "malware"


def test_entity_type_change_updates_alias_entity_type(db_session: Session) -> None:
    eid = _entity(db_session, "malware", "Cobalt Strike")
    _alias(db_session, eid, "cobalt strike")
    db_session.execute(text("UPDATE entities SET type = 'tool' WHERE id = :e"), {"e": eid})
    got = db_session.execute(
        text("SELECT entity_type FROM entity_aliases WHERE entity_id = :e"), {"e": eid}
    ).scalar_one()
    assert got == "tool"


def test_alias_unique_per_type_not_across_types(db_session: Session) -> None:
    actor = _entity(db_session, "intrusion-set", "Lazarus")
    other = _entity(db_session, "intrusion-set", "Lazarus Group")
    tool = _entity(db_session, "tool", "Lazarus")
    _alias(db_session, actor, "lazarus")
    _alias(db_session, tool, "lazarus")  # beda tipe: boleh
    with pytest.raises(IntegrityError), db_session.begin_nested():
        _alias(db_session, other, "lazarus")  # tipe sama: ditolak walau SQL mentah


def test_downgrade_drops_everything(db_session: Session) -> None:
    _run(db_session, "downgrade")
    left = db_session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables WHERE table_name IN"
            " ('entities','entity_aliases','relationships','entity_mentions','entity_watches',"
            "'entity_profiles','reference_snapshots')"
        )
    ).scalar_one()
    assert left == 0
    assert not db_session.execute(
        text("SELECT 1 FROM pg_proc WHERE proname = 'entity_aliases_sync_type'")
    ).first()
    _run(db_session, "upgrade")  # bolak-balik harus mulus


def test_downgrade_restores_legacy_rows_and_sequences(db_session: Session) -> None:
    """Baris lama -> upgrade (tabel jadi _legacy_*) -> downgrade: baris kembali dengan id-nya dan
    sekuens id melanjutkan dari max(id)."""
    s = db_session
    _run(s, "downgrade")
    s.merge(Client(client_id="dgc", name="DG"))
    art = Article(url="https://dg.example/a", url_hash="dg-a", title="t", source="dg")
    s.add(art)
    s.flush()
    seeded = {
        "article_threat_actors": _one(
            s,
            "INSERT INTO article_threat_actors (article_id, threat_actor, source)"
            " VALUES (:a, 'Dg Actor', 'llm') RETURNING id",
            a=art.id,
        ),
        "ta_watchlist": _one(
            s,
            "INSERT INTO ta_watchlist (name, client_id) VALUES ('Dg Actor', 'dgc') RETURNING id",
        ),
        "ta_whitelist": _one(s, "INSERT INTO ta_whitelist (name) VALUES ('dg x') RETURNING id"),
    }
    _run(s, "upgrade")
    assert _one(s, "SELECT relkind FROM pg_class WHERE relname = 'article_threat_actors'") == "v"
    _run(s, "downgrade")
    for table, row_id in seeded.items():
        assert _one(s, f"SELECT count(*) FROM {table} WHERE id = :i", i=row_id) == 1
        nxt = _one(s, f"SELECT nextval('{table}_id_seq')")
        assert nxt > _one(s, f"SELECT max(id) FROM {table}")
    assert (
        _one(s, "SELECT count(*) FROM article_cves WHERE article_id = :a", a=art.id) == 0
    )  # tabel tanpa sekuens ikut kembali
    _run(s, "upgrade")


def test_upgrade_locks_uppercases_indexes_and_analyzes(db_session: Session) -> None:
    """M7: tabel lama dikunci EXCLUSIVE di awal (tulisan kode lama selama backfill menunggu,
    tidak hilang). M8: CVE huruf kecil di tabel lama jadi `CVE-...`. M9: indeks
    `relationships.source_indicator_id`. M10: ANALYZE tabel baru (reltuples terisi)."""
    s = db_session
    _run(s, "downgrade")
    art = Article(url="https://up.example/a", url_hash="up-a", title="t", source="up")
    s.add(art)
    s.flush()
    s.execute(
        text(
            "INSERT INTO article_cves (article_id, cve_id, in_title)"
            " VALUES (:a, 'cve-2026-4242', false)"
        ),
        {"a": art.id},
    )
    _run(s, "upgrade")
    locked = set(
        s.scalars(
            text(
                "SELECT c.relname FROM pg_locks l JOIN pg_class c ON c.oid = l.relation"
                " WHERE l.pid = pg_backend_pid() AND l.mode = 'ExclusiveLock'"
                " AND c.relname LIKE '\\_legacy\\_%'"
            )
        )
    )
    assert locked == {"_legacy_" + t for t in migration._COMPAT}
    assert s.execute(
        text("SELECT name, external_id FROM entities WHERE lower(name) = 'cve-2026-4242'")
    ).all() == [("CVE-2026-4242", "CVE-2026-4242")]
    assert (
        _one(
            s,
            "SELECT count(*) FROM pg_indexes"
            " WHERE indexname = 'ix_relationships_source_indicator_id'",
        )
        == 1
    )
    assert _one(s, "SELECT reltuples FROM pg_class WHERE relname = 'entities'") == _one(
        s, "SELECT count(*) FROM entities"
    )


# --- backfill (Task 3): tabel lama -> entitas/alias/relasi/mention, set-based di upgrade() ---


def _one(session: Session, sql: str, **params: object) -> Any:
    return session.execute(text(sql), params).scalar_one()


@pytest.fixture
def bf(db_session: Session) -> Iterator[dict[str, Any]]:
    """Mundur ke skema lama, semai tabel lama, lalu jalankan `upgrade()` (dengan backfill)."""
    s = db_session
    _run(s, "downgrade")
    ex = s.execute
    # baris induk lewat ORM supaya default sisi-Python (kolom NOT NULL tanpa default DB) terisi
    s.merge(Client(client_id="bfc", name="BF"))
    arts = [
        Article(
            url=f"https://bf.example/{k}", url_hash=f"bf-{k}", title="t", source="bf", posted_on=d
        )
        for k, d in (("a1", datetime.date(2026, 3, 1)), ("a2", None))
    ]
    ind = Indicator(type="ip", value="192.0.2.9")
    cve = CveTracker(cve_id="CVE-2023-9999", client_id="bfc", tech="x")
    # ATT&CK: alias 'Cozy Bear' dipakai dua grup (pemilik pertama menurut stix_id menang);
    # dua teknik senama beda id (Ruling 7)
    attack: list[Any] = [
        AttackGroup(
            stix_id="intrusion-set--g1",
            group_id="G0016",
            name="APT29",
            aliases=["APT29", "Cozy Bear", "NOBELIUM"],
        ),
        AttackGroup(
            stix_id="intrusion-set--g2",
            group_id="G0007",
            name="APT28",
            aliases=["APT28", "Fancy Bear", "Cozy Bear"],
        ),
        AttackSoftware(
            stix_id="malware--m1",
            software_id="S0367",
            name="Emotet",
            software_type="malware",
            aliases=["Emotet", "Geodo"],
        ),
        AttackSoftware(
            stix_id="tool--t1",
            software_id="S0002",
            name="Mimikatz",
            software_type="tool",
            aliases=["Mimikatz"],
        ),
        *(
            AttackTechnique(stix_id=sid, attack_id=tid, name=name)
            for sid, tid, name in (
                ("attack-pattern--a1", "T1566.001", "Spearphishing Attachment"),
                ("attack-pattern--a2", "T1598.002", "Spearphishing Attachment"),
                ("attack-pattern--a3", "T1566", "Phishing"),
            )
        ),
        *(
            AttackRelationship(
                stix_id=f"relationship--{rid}",
                relationship_type=rt,
                source_ref=src,
                target_ref=dst,
                domain="enterprise",
            )
            for rid, rt, src, dst in (
                ("r1", "uses", "intrusion-set--g1", "malware--m1"),
                ("r2", "uses", "intrusion-set--g1", "attack-pattern--a1"),
                ("r3", "subtechnique-of", "attack-pattern--a1", "attack-pattern--a3"),
                ("r4", "revoked-by", "attack-pattern--a2", "attack-pattern--a1"),
                ("r5", "uses", "campaign--c1", "malware--m1"),
                ("r6", "mitigates", "course-of-action--x", "attack-pattern--a1"),
            )
        ),
    ]
    victims = [
        RansomwareVictim(
            offset_key=k, group_name=g, victim=v, country_code=c, industry=i, discovered=d
        )
        for k, g, v, c, i, d in (
            ("k1", "LockBit", "Acme Corp", "DE", "Manufacturing", datetime.date(2026, 1, 2)),
            ("k2", "lockbit", "ACME  corp", "DE", "General", datetime.date(2026, 1, 5)),
            # nama korban 350 karakter (kolom lama varchar(500)) -> dipotong 300
            ("k3", "LockBit", "V" * 350, "de", None, datetime.date(2026, 1, 7)),
        )
    ]
    pirs = [
        PIRRequirement(
            title="p", client_id="bfc", criteria={"threat_actors": ["Scattered Spider", "APT29"]}
        ),
        # isian bebas pengguna: hanya string non-kosong yang jadi entitas, string panjang dipotong
        PIRRequirement(
            title="p2",
            client_id="bfc",
            criteria={"threat_actors": [None, 123, {"a": 1}, "", "   ", "L" * 301]},
        ),
        PIRRequirement(title="p3", client_id="bfc", criteria={}),
        PIRRequirement(title="p4", client_id="bfc", criteria={"threat_actors": "Not A List"}),
    ]
    s.add_all([*arts, ind, cve, *attack, *victims, *pirs])
    s.flush()
    ids: dict[str, Any] = {
        "a1": arts[0].id,
        "a2": arts[1].id,
        "ind": ind.id,
        "cve": cve.id,
        # stories.feed_changed_at belum ada di skema lama: SQL mentah, bukan ORM
        "story": _one(
            s,
            "INSERT INTO stories (title, lead_source, created_at, last_seen_at)"
            " VALUES ('s', 'bf', '2026-01-01Z', '2026-02-01Z') RETURNING id",
        ),
    }
    a1, a2 = ids["a1"], ids["a2"]
    ex = s.execute
    # sembilan tabel tautan
    p = {"a1": a1, "a2": a2, "ind": ids["ind"], "cve": ids["cve"]}
    for sql in (
        "INSERT INTO article_threat_actors (article_id, threat_actor, source) VALUES"
        " (:a1, 'Cozy bear', 'dictionary'), (:a1, 'Apt29', 'dictionary'),"
        " (:a2, 'Volt typhoon', 'llm'), (:a2, '   ', 'dictionary')",
        "INSERT INTO article_malware (article_id, name, kind, source) VALUES"
        " (:a1, 'Emotet', 'malware', 'dictionary'), (:a1, 'Mimikatz', 'tool', 'dictionary'),"
        " (:a2, 'NewLoader', 'malware', 'llm'), (:a2, '', 'malware', 'dictionary')",
        "INSERT INTO article_ttps (article_id, ttp_id, ttp_name, extracted_id, extracted_name,"
        " source, evidence) VALUES"
        " (:a1, 'T1566.001', 'Spearphishing Attachment', 'T1193', 'Spearphishing Attachment',"
        "  'llm', 'sent a lure'),"
        " (:a2, 'T1086', 'PowerShell', NULL, NULL, 'keyword', NULL)",
        "INSERT INTO article_cves (article_id, cve_id, in_title, first_seen_at) VALUES"
        " (:a1, 'CVE-2024-1234', true, '2026-03-02'), (:a2, 'CVE-2024-1234', false, '2026-03-03')",
        "INSERT INTO article_countries (article_id, country_code, role) VALUES"
        " (:a1, 'US', 'target'), (:a1, 'US', 'origin'), (:a2, 'ZZ', 'target'),"
        " (:a2, 'us', 'origin')",
        "INSERT INTO article_industries (article_id, industry, source) VALUES"
        " (:a1, 'Cloud Services', 'llm'), (:a1, 'Information Technology & Software', 'llm'),"
        " (:a1, 'General', 'llm'), (:a2, 'Underwater Basketry', 'llm')",
        "INSERT INTO indicator_threat_actors (indicator_id, threat_actor) VALUES (:ind, 'APT28')",
        "INSERT INTO cve_threat_actors (cve_tracker_id, threat_actor) VALUES (:cve, 'Fancy Bear')",
        "INSERT INTO cve_ttps (cve_tracker_id, ttp_id, ttp_name)"
        " VALUES (:cve, 'T1566', 'Phishing')",
        "INSERT INTO ta_watchlist (name, client_id) VALUES"
        " ('apt29', 'bfc'), ('Cozy Bear', 'bfc'), ('Shinyhunters', 'bfc')",
        "INSERT INTO ta_profiles (actor_name, profile, generated_at) VALUES"
        " ('Shinyhunters', '{\"summary\": \"x\"}', '2026-01-01')",
        "INSERT INTO ta_whitelist (name) VALUES ('testactor'), ('Volt Typhoon')",
    ):
        params = {k: v for k, v in p.items() if f":{k}" in sql}
        ex(text(sql), params)
    _run(s, "upgrade")
    yield ids


def _entity_id(s: Session, type_: str, alias: str) -> int:
    return _one(
        s,
        "SELECT entity_id FROM entity_aliases WHERE entity_type = :t AND alias_norm = :n",
        t=type_,
        n=alias.lower(),
    )


def _mentions(s: Session, where: str, **params: object) -> list[tuple[Any, ...]]:
    return [
        tuple(r)
        for r in s.execute(
            text(
                "SELECT e.type, e.name, m.matched_alias, m.method, m.role FROM entity_mentions m"
                f" JOIN entities e ON e.id = m.entity_id WHERE {where}"
                " ORDER BY e.type, e.name, m.role"
            ),
            params,
        )
    ]


def test_mention_counts_equal_per_old_table(db_session: Session, bf: dict[str, Any]) -> None:
    s = db_session
    a1, a2 = bf["a1"], bf["a2"]
    assert _mentions(s, "m.article_id = :a", a=a1) == [
        ("attack-pattern", "Spearphishing Attachment", "T1566.001", "llm", None),
        ("identity", "Technology", "Cloud Services", "llm", None),  # 2 label -> 1 sektor
        ("intrusion-set", "APT29", "Cozy bear", "dictionary", None),  # 2 ejaan -> 1, id kecil
        ("location", "United States", "US", "legacy", "origin"),
        ("location", "United States", "US", "legacy", "target"),
        ("malware", "Emotet", "Emotet", "dictionary", None),
        ("tool", "Mimikatz", "Mimikatz", "dictionary", None),
        ("vulnerability", "CVE-2024-1234", "CVE-2024-1234", "legacy", None),
    ]  # "General" tidak menghasilkan mention
    assert _mentions(s, "m.article_id = :a", a=a2) == [
        ("attack-pattern", "PowerShell", "T1086", "keyword", None),
        ("identity", "Underwater Basketry", "Underwater Basketry", "llm", None),
        ("intrusion-set", "Volt typhoon", "Volt typhoon", "llm", None),
        ("location", "United States", "us", "legacy", "origin"),  # kode huruf kecil
        ("location", "ZZ", "ZZ", "legacy", "target"),
        ("malware", "NewLoader", "NewLoader", "llm", None),
        ("vulnerability", "CVE-2024-1234", "CVE-2024-1234", "legacy", None),
    ]
    assert _mentions(s, "m.indicator_id = :i", i=bf["ind"]) == [
        ("intrusion-set", "APT28", "APT28", "legacy", None)
    ]
    assert _mentions(s, "m.cve_tracker_id = :c", c=bf["cve"]) == [
        ("attack-pattern", "Phishing", "T1566", "legacy", None),
        ("intrusion-set", "APT28", "Fancy Bear", "legacy", None),
    ]
    ttp = s.execute(
        text(
            "SELECT evidence, extracted FROM entity_mentions"
            " WHERE article_id = :a AND matched_alias = 'T1566.001'"
        ),
        {"a": a1},
    ).one()
    assert ttp == (
        "sent a lure",
        {"extracted_id": "T1193", "extracted_name": "Spearphishing Attachment"},
    )
    cve = _one(
        s,
        "SELECT extracted FROM entity_mentions WHERE article_id = :a AND matched_alias LIKE 'CVE%'",
        a=a1,
    )
    assert cve["in_title"] is True and cve["first_seen_at"].startswith("2026-03-02")
    legacy_ttp = s.execute(
        text("SELECT source, external_id FROM entities WHERE name = 'PowerShell'")
    ).one()
    assert legacy_ttp == ("legacy", "T1086")
    sector = s.execute(
        text("SELECT source, identity_class FROM entities WHERE name = 'Underwater Basketry'")
    ).one()
    assert sector == ("legacy", "class")
    assert (
        _one(
            s,
            "SELECT count(*) FROM entities WHERE type = 'vulnerability' AND name = 'CVE-2023-9999'"
            " AND external_id = 'CVE-2023-9999' AND source = 'cve'",
        )
        == 1
    )


def test_no_orphans(db_session: Session, bf: dict[str, Any]) -> None:
    assert (
        _one(
            db_session,
            "SELECT count(*) FROM entity_mentions m LEFT JOIN entities e ON e.id = m.entity_id"
            " WHERE e.id IS NULL OR e.merged_into_id IS NOT NULL",
        )
        == 0
    )
    # setiap entitas punya minimal satu alias (teknik: id-nya)
    assert (
        _one(
            db_session,
            "SELECT count(*) FROM entities e WHERE NOT EXISTS"
            " (SELECT 1 FROM entity_aliases a WHERE a.entity_id = e.id)",
        )
        == 0
    )


def test_attack_backfill(db_session: Session, bf: dict[str, Any]) -> None:
    s = db_session
    rows = s.execute(
        text(
            "SELECT stix_id, type, name, external_id, source FROM entities"
            " WHERE stix_id IN ('intrusion-set--g1', 'intrusion-set--g2', 'malware--m1',"
            " 'tool--t1', 'attack-pattern--a1', 'attack-pattern--a2', 'attack-pattern--a3')"
            " ORDER BY stix_id"
        )
    ).all()
    assert [tuple(r) for r in rows] == [
        ("attack-pattern--a1", "attack-pattern", "Spearphishing Attachment", "T1566.001", "attack"),
        ("attack-pattern--a2", "attack-pattern", "Spearphishing Attachment", "T1598.002", "attack"),
        ("attack-pattern--a3", "attack-pattern", "Phishing", "T1566", "attack"),
        ("intrusion-set--g1", "intrusion-set", "APT29", "G0016", "attack"),
        ("intrusion-set--g2", "intrusion-set", "APT28", "G0007", "attack"),
        ("malware--m1", "malware", "Emotet", "S0367", "attack"),
        ("tool--t1", "tool", "Mimikatz", "S0002", "attack"),
    ]
    g1 = _entity_id(s, "intrusion-set", "APT29")
    aliases = s.execute(
        text("SELECT alias_norm, source FROM entity_aliases WHERE entity_id = :e ORDER BY 1"),
        {"e": g1},
    ).all()
    assert [tuple(r) for r in aliases] == [
        ("apt29", "attack"),
        ("cozy bear", "attack"),
        ("nobelium", "attack"),
    ]
    assert _entity_id(s, "intrusion-set", "fancy bear") != g1
    a1 = _one(s, "SELECT id FROM entities WHERE stix_id = 'attack-pattern--a1'")
    assert [
        r[0]
        for r in s.execute(text("SELECT alias FROM entity_aliases WHERE entity_id = :e"), {"e": a1})
    ] == ["T1566.001"]
    rels = s.execute(
        text(
            "SELECT r.stix_id, r.relationship_type, r.confidence, r.provenance FROM relationships r"
            " WHERE r.provenance = 'attack' ORDER BY r.stix_id"
        )
    ).all()
    assert [tuple(r) for r in rels] == [
        ("relationship--r1", "uses", 85, "attack"),
        ("relationship--r2", "uses", 85, "attack"),
        ("relationship--r3", "subtechnique-of", 85, "attack"),
    ]


def test_old_names_resolve_to_attack_alias(db_session: Session, bf: dict[str, Any]) -> None:
    got = db_session.execute(
        text(
            "SELECT e.stix_id, m.matched_alias FROM entity_mentions m"
            " JOIN entities e ON e.id = m.entity_id"
            " WHERE m.article_id = :a AND e.type = 'intrusion-set'"
        ),
        {"a": bf["a1"]},
    ).all()
    assert [tuple(r) for r in got] == [("intrusion-set--g1", "Cozy bear")]


def test_ransomware(db_session: Session, bf: dict[str, Any]) -> None:
    s = db_session
    victim = s.execute(
        text("SELECT id, name, identity_class, source FROM entities WHERE name = 'Acme Corp'")
    ).one()
    assert tuple(victim)[1:] == ("Acme Corp", "organization", "ransomware")
    group = s.execute(
        text("SELECT id, type, source FROM entities WHERE lower(name) = 'lockbit'")
    ).one()
    assert tuple(group)[1:] == ("intrusion-set", "legacy")
    rels = s.execute(
        text(
            "SELECT r.relationship_type, r.source_entity_id, t.name, r.confidence, r.provenance,"
            " r.first_seen::date::text, r.last_seen::date::text, r.stix_id LIKE 'relationship--%'"
            " FROM relationships r JOIN entities t ON t.id = r.target_entity_id"
            " WHERE r.provenance = 'ransomware' AND :v IN (r.source_entity_id, r.target_entity_id)"
            " ORDER BY 1"
        ),
        {"v": victim[0]},
    ).all()
    assert [tuple(r) for r in rels] == [
        ("located-at", victim[0], "Germany", 50, "ransomware", "2026-01-02", "2026-01-05", True),
        ("targets", group[0], "Acme Corp", 50, "ransomware", "2026-01-02", "2026-01-05", True),
    ]
    # industri ransomware lewat alias sektor; "General" tidak membuat apa-apa
    assert _one(s, "SELECT count(*) FROM entities WHERE lower(name) = 'general'") == 0
    assert _entity_id(s, "identity", "manufacturing") == _one(
        s, "SELECT id FROM entities WHERE source = 'sector' AND external_id = 'manufacturing'"
    )


def test_watch_profile_whitelist_moved(db_session: Session, bf: dict[str, Any]) -> None:
    s = db_session
    watches = (
        s.execute(
            text(
                "SELECT e.name FROM entity_watches w JOIN entities e ON e.id = w.entity_id"
                " WHERE w.client_id = 'bfc' ORDER BY 1"
            )
        )
        .scalars()
        .all()
    )
    assert watches == ["APT29", "Shinyhunters"]  # 'apt29' + 'Cozy Bear' -> satu watch
    prof = s.execute(
        text(
            "SELECT e.name, p.profile FROM entity_profiles p JOIN entities e ON e.id = p.entity_id"
        )
    ).all()
    assert [tuple(r) for r in prof] == [("Shinyhunters", {"summary": "x"})]
    sup = s.execute(text("SELECT name, source FROM entities WHERE suppressed ORDER BY 1")).all()
    assert [tuple(r) for r in sup] == [("Volt typhoon", "legacy"), ("testactor", "legacy")]


def test_seen_and_clocks(db_session: Session, bf: dict[str, Any]) -> None:
    s = db_session
    seen = s.execute(
        text(
            "SELECT first_seen = '2026-03-01T00:00:00Z'::timestamptz,"
            " last_seen = first_seen FROM entities WHERE stix_id = 'intrusion-set--g1'"
        )
    ).one()
    assert tuple(seen) == (True, True)
    cve = s.execute(
        text(
            "SELECT e.first_seen = '2026-03-01T00:00:00Z'::timestamptz,"
            " e.last_seen = (SELECT created_at FROM articles WHERE id = :a2)"
            " FROM entities e WHERE e.name = 'CVE-2024-1234'"
        ),
        {"a2": bf["a2"]},
    ).one()
    assert tuple(cve) == (True, True)  # a2 tanpa posted_on -> created_at
    assert _one(s, "SELECT count(*) FROM entities WHERE feed_changed_at < created_at") == 0
    assert _one(s, "SELECT count(*) FROM relationships WHERE feed_changed_at < created_at") == 0
    assert _one(
        s,
        "SELECT feed_changed_at = '2026-02-01'::timestamptz FROM stories WHERE id = :i",
        i=bf["story"],
    )


def test_pir_actor_criteria_become_entities(db_session: Session, bf: dict[str, Any]) -> None:
    s = db_session
    assert (
        _one(
            s,
            "SELECT source FROM entities"
            " WHERE type = 'intrusion-set' AND name = 'Scattered Spider'",
        )
        == "legacy"
    )
    assert _entity_id(s, "intrusion-set", "apt29") == _one(
        s, "SELECT id FROM entities WHERE stix_id = 'intrusion-set--g1'"
    )
    long = _one(s, "SELECT name FROM entities WHERE type = 'intrusion-set' AND name LIKE 'LLL%'")
    assert long == "L" * 300
    assert (
        _one(
            s,
            "SELECT count(*) FROM entities WHERE type = 'intrusion-set'"
            " AND name IN ('123', '{\"a\": 1}', 'null', 'Not A List')",
        )
        == 0
    )
    crit = _one(s, "SELECT criteria FROM pir_requirements WHERE title = 'p'")
    assert crit == {"threat_actors": ["Scattered Spider", "APT29"]}  # baris PIR tidak diubah


def test_reference_stix_ids_from_generator(db_session: Session, bf: dict[str, Any]) -> None:
    from cti_core.entity import entity_stix_id

    s = db_session
    us = s.execute(
        text(
            "SELECT name, source, stix_id FROM entities"
            " WHERE type = 'location' AND external_id = 'US'"
        )
    ).one()
    assert tuple(us) == ("United States", "iso", entity_stix_id("location", "United States"))
    tech = s.execute(
        text("SELECT name, identity_class, stix_id FROM entities WHERE external_id = 'technology'")
    ).one()
    assert tuple(tech) == ("Technology", "class", entity_stix_id("identity", "Technology"))


def test_victim_name_truncated(db_session: Session, bf: dict[str, Any]) -> None:
    s = db_session
    vid = _one(s, "SELECT id FROM entities WHERE type = 'identity' AND name = :n", n="V" * 300)
    rels = s.execute(
        text(
            "SELECT r.relationship_type, t.name FROM relationships r"
            " JOIN entities t ON t.id = r.target_entity_id"
            " WHERE :v IN (r.source_entity_id, r.target_entity_id) ORDER BY 1"
        ),
        {"v": vid},
    ).all()
    assert [tuple(r) for r in rels] == [("located-at", "Germany"), ("targets", "V" * 300)]


def test_blank_old_names_dropped(db_session: Session, bf: dict[str, Any]) -> None:
    s = db_session
    assert _one(s, "SELECT count(*) FROM entities WHERE btrim(name) = ''") == 0
    assert _one(s, "SELECT count(*) FROM entity_aliases WHERE alias_norm = ''") == 0


def test_unknown_industry_labels_become_legacy_sectors(
    db_session: Session, bf: dict[str, Any]
) -> None:
    unknown = (
        db_session.execute(
            text(
                "SELECT name FROM entities WHERE type = 'identity' AND identity_class = 'class'"
                " AND source = 'legacy' ORDER BY name"
            )
        )
        .scalars()
        .all()
    )
    print("label industri tak dikenal:", unknown)  # spec 3.3: daftar label yang tak terpetakan
    assert unknown == ["Underwater Basketry"]
