"""Penulis P7c Task 8 di Postgres beneran: pipeline (persist), kamus Tier 1, sink ransomware dan
seed fase 10 menulis `entity_mentions`/`entities`/`relationships` lewat resolver, bukan tabel link
lama (yang kini view kompatibilitas)."""

from __future__ import annotations

import datetime
from typing import Any

from cti_core.attack_ttp import NormalizedTTP
from cti_core.db.models.article import Article
from cti_core.db.models.auth import Client
from cti_core.db.models.entity import Entity, EntityAlias, EntityProfile, EntityWatch
from cti_core.db.repositories.article import ArticleRepo, MentionInput
from cti_core.db.repositories.ransomware import RansomwareVictimRepo
from cti_core.db.repositories.threat_reference import load_entity_sources
from cti_core.entity import alias_norm
from cti_enrich.routing import RoutingResult
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.persist import persist
from cti_enrich.stages.score import ScoreResult
from cti_enrich.stages.tier1 import Tier1Result
from cti_enrich.tier1.dictionary import build_entity_dictionary
from cti_enrich.tier1.entities import EntityHit, match_entities
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tests.integration.entity_support import seed_entity
from tools.seed import fase10_reference_data as seed
from tools.seed._dump import MemoryDump

_UTC = datetime.UTC


def _mentions(s: Session, article_id: int) -> list[tuple[Any, ...]]:
    return [
        tuple(r)
        for r in s.execute(
            text(
                "SELECT e.type, e.name, m.method, m.matched_alias, m.role, m.evidence, m.extracted"
                "  FROM entity_mentions m JOIN entities e ON e.id = m.entity_id"
                " WHERE m.article_id = :a ORDER BY e.type, e.name, m.role"
            ),
            {"a": article_id},
        ).all()
    ]


def _persist(
    s: Session,
    url: str,
    *,
    posted_on: datetime.date | None = None,
    actors: list[str] | None = None,
    tier1: Tier1Result | None = None,
) -> Article:
    return persist(
        session=s,
        url=url,
        title="APT29 exploits CVE-2026-1234 in VPN",
        source="s",
        scraper_id=None,
        posted_on=posted_on,
        classify_result=ClassifyResult(
            related_cyber=True, confidence=0.9, victim_countries=["Indonesia"]
        ),
        score_result=None,
        routing_result=RoutingResult(
            news_type="General", alert_topics=[], msg_data="", threat_actors=actors or []
        ),
        ttp_result=None,
        ioc_data={"cves": ["cve-2026-1234"]},
        c2_indicator=False,
        tier1=tier1,
        merged_ttps=[
            NormalizedTTP(
                "T1190",
                "Exploit Public-Facing Application",
                extracted_id="T1190",
                extracted_name="exploit vpn",
                source="llm",
                evidence="exploited a VPN appliance",
            )
        ],
        industries=(["Finance & Insurance", "General"], "keyword"),
    )


def _seed_attack(s: Session) -> None:
    seed_entity(s, "intrusion-set", "APT29", "Cozy Bear", external_id="G0016")
    seed_entity(s, "tool", "Cobalt Strike", external_id="S0154")
    seed_entity(
        s,
        "attack-pattern",
        "Exploit Public-Facing Application",
        external_id="T1190",
    )


def test_persist_writes_mentions(db_session: Session) -> None:
    _seed_attack(db_session)
    tier1 = Tier1Result(
        entities=[
            EntityHit("APT29", "actor", "Cozy Bear", 0),
            EntityHit("Cobalt Strike", "tool", "cobalt strike", 10),
        ]
    )

    article = _persist(db_session, "https://w.example/1", actors=["Apt29"], tier1=tier1)

    assert _mentions(db_session, article.id) == [
        (
            "attack-pattern",
            "Exploit Public-Facing Application",
            "llm",
            "T1190",
            None,
            "exploited a VPN appliance",
            {"extracted_id": "T1190", "extracted_name": "exploit vpn"},
        ),
        ("identity", "Financial Services", "keyword", "Finance & Insurance", None, None, None),
        ("intrusion-set", "APT29", "dictionary", "Cozy Bear", None, None, None),
        ("location", "Indonesia", "llm", "ID", "mentioned", None, None),
        ("location", "Indonesia", "llm", "ID", "victim", None, None),
        ("tool", "Cobalt Strike", "dictionary", "cobalt strike", None, None, None),
        ("vulnerability", "CVE-2026-1234", "explicit", "CVE-2026-1234", None, None,
         {"in_title": True}),
    ]  # fmt: skip
    # helper baca ORM: nama entitas kanonik, urut id mention, tanpa duplikat
    assert article.entity_names("intrusion-set") == ["APT29"]
    assert article.entity_names("location") == ["Indonesia"]
    assert [m.role for m in article.mentions_of("location")] == ["victim", "mentioned"]

    # replay: idempoten, tanpa duplikat; industri yang hilang dibuang
    again = _persist(db_session, "https://w.example/1", actors=["Apt29"], tier1=tier1)
    assert again.id == article.id
    assert len(_mentions(db_session, article.id)) == 7


def test_persist_again_removes_dropped_mentions_and_keeps_cve(db_session: Session) -> None:
    """Jalur hapus sebagian `set_enrichment` (`delete_other_mentions`): role negara, aktor, TTP
    dan sektor yang hilang dibuang; CVE (bukan tipe enrichment) dan baris yang tetap bertahan;
    mention lokasi ber-role NULL (mis. dari view kompatibilitas) ikut terhapus."""
    _seed_attack(db_session)
    seed_entity(
        db_session, "attack-pattern", "Command and Scripting Interpreter", external_id="T1059"
    )
    url = "https://w.example/partial"

    def run(**kw: Any) -> Article:
        base: dict[str, Any] = {
            "session": db_session,
            "url": url,
            "title": "APT29 exploits CVE-2026-1234 in VPN",
            "source": "s",
            "scraper_id": None,
            "posted_on": None,
            "ttp_result": None,
            "c2_indicator": False,
        }
        return persist(**base, **kw)

    first = run(
        classify_result=ClassifyResult(
            related_cyber=True, confidence=0.9, victim_countries=["Indonesia"]
        ),
        score_result=None,
        routing_result=RoutingResult(
            news_type="General", alert_topics=[], msg_data="", threat_actors=["Apt29"]
        ),
        ioc_data={"cves": ["CVE-2026-1234"]},
        merged_ttps=[
            NormalizedTTP("T1190", "Exploit Public-Facing Application", source="llm"),
            NormalizedTTP("T1059", "Command and Scripting Interpreter", source="llm"),
        ],
        industries=(["Finance & Insurance"], "llm"),
    )
    repo = ArticleRepo(db_session)
    # role NULL untuk negara yang TETAP disebut (ID/mentioned): `(entity, role) IN (...)` bernilai
    # NULL untuk baris ini, jadi predikat tanpa IS NULL eksplisit tidak pernah menghapusnya
    repo.add_mentions(first, [MentionInput("location", "ID", "legacy", "ID", external_id="ID")])
    assert {(m[0], m[1], m[4]) for m in _mentions(db_session, first.id)} >= {
        ("location", "Indonesia", "victim"),
        ("location", "Indonesia", "mentioned"),
        ("location", "Indonesia", None),
        ("attack-pattern", "Command and Scripting Interpreter", None),
    }

    run(
        classify_result=ClassifyResult(related_cyber=True, confidence=0.9),
        score_result=ScoreResult(mentioned_countries=["Indonesia"]),
        routing_result=RoutingResult(
            news_type="General",
            alert_topics=[],
            msg_data="",
            threat_actors=["Lazarus"],
            is_global_branch=True,  # tanpa fallback victim: ID hanya `mentioned`
        ),
        ioc_data={},  # CVE tidak dikirim ulang: mention lamanya harus bertahan
        merged_ttps=[NormalizedTTP("T1190", "Exploit Public-Facing Application", source="llm")],
        industries=(["Healthcare & Life Sciences"], "llm"),
    )

    assert [(m[0], m[1], m[2], m[3], m[4]) for m in _mentions(db_session, first.id)] == [
        ("attack-pattern", "Exploit Public-Facing Application", "llm", "T1190", None),
        ("identity", "Healthcare", "llm", "Healthcare & Life Sciences", None),
        ("intrusion-set", "Lazarus", "dictionary", "Lazarus", None),
        ("location", "Indonesia", "llm", "ID", "mentioned"),
        ("vulnerability", "CVE-2026-1234", "explicit", "CVE-2026-1234", None),
    ]


def test_sector_label_resolving_to_organization_is_dropped(db_session: Session) -> None:
    org = seed_entity(
        db_session, "identity", "Underwater Basketry", source="ransomware", alias_source="legacy"
    )
    org.identity_class = "organization"  # korban bernama seperti label industri
    db_session.flush()
    repo = ArticleRepo(db_session)
    article = repo.upsert(url="https://w.example/org", title="t", source="s")

    repo.set_enrichment(article, industries=["Underwater Basketry", "Finance & Insurance"])

    assert article.entity_names("identity") == ["Financial Services"]


def test_add_tier1_records_matched_alias(db_session: Session) -> None:
    _seed_attack(db_session)
    repo = ArticleRepo(db_session)
    article = repo.upsert(url="https://w.example/t1", title="t", source="s")

    counts = repo.add_tier1(
        article,
        ttps=[],
        threat_actors=["Apt29"],
        malware=[("Cobalt Strike", "tool")],
        industries=[],
        aliases={"apt29": "Cozy Bear", "cobalt strike": "CS beacon"},
    )

    assert counts["threat_actors"] == 1 and counts["malware"] == 1
    assert [(m[1], m[3]) for m in _mentions(db_session, article.id)] == [
        ("APT29", "Cozy Bear"),
        ("Cobalt Strike", "CS beacon"),
    ]


def test_persist_skips_suppressed_and_follows_merge(db_session: Session) -> None:
    _seed_attack(db_session)
    noisy = seed_entity(db_session, "intrusion-set", "Noisy Crew", source="legacy")
    noisy.suppressed = True
    old = seed_entity(db_session, "intrusion-set", "Old Name", source="legacy")
    apt29 = db_session.scalars(select(Entity).where(Entity.name == "APT29")).one()
    db_session.execute(
        text("UPDATE entity_aliases SET entity_id = :t WHERE entity_id = :o"),
        {"t": apt29.id, "o": old.id},
    )
    old.merged_into_id = apt29.id
    db_session.flush()

    article = _persist(db_session, "https://w.example/2", actors=["Noisy crew", "Old name"])

    actors = [m for m in _mentions(db_session, article.id) if m[0] == "intrusion-set"]
    assert actors == [("intrusion-set", "APT29", "dictionary", "Old name", None, None, None)]


def test_persist_updates_seen(db_session: Session) -> None:
    _seed_attack(db_session)
    _persist(
        db_session, "https://w.example/3", posted_on=datetime.date(2026, 10, 5), actors=["Apt29"]
    )
    _persist(
        db_session, "https://w.example/4", posted_on=datetime.date(2026, 10, 1), actors=["Apt29"]
    )
    _persist(
        db_session, "https://w.example/5", posted_on=datetime.date(2026, 10, 9), actors=["Apt29"]
    )

    apt29 = db_session.scalars(select(Entity).where(Entity.name == "APT29")).one()
    db_session.refresh(apt29)
    assert apt29.first_seen == datetime.datetime(2026, 10, 1, tzinfo=_UTC)
    assert apt29.last_seen == datetime.datetime(2026, 10, 9, tzinfo=_UTC)
    cve = db_session.scalars(select(Entity).where(Entity.name == "CVE-2026-1234")).one()
    assert cve.first_seen == datetime.datetime(2026, 10, 1, tzinfo=_UTC)


def test_add_mentions_is_idempotent(db_session: Session) -> None:
    _seed_attack(db_session)
    repo = ArticleRepo(db_session)
    article = repo.upsert(url="https://w.example/6", title="t", source="s")
    hits = [
        MentionInput("intrusion-set", "Cozy Bear", "analyst", "Cozy Bear"),
        MentionInput("intrusion-set", "APT29", "analyst", "APT29"),
    ]

    assert repo.add_mentions(article, hits) == 1
    assert repo.add_mentions(article, hits) == 0
    assert article.entity_names() == ["APT29"]


def _dictionary(s: Session) -> Any:
    return build_entity_dictionary(*load_entity_sources(s))


def test_dictionary_uses_entity_name_as_canonical(db_session: Session) -> None:
    _seed_attack(db_session)

    hits = match_entities("Researchers tied the campaign to Cozy Bear.", _dictionary(db_session))

    assert [(h.canonical, h.kind, h.matched) for h in hits] == [("APT29", "actor", "Cozy Bear")]


def test_dictionary_version_changes_with_alias(db_session: Session) -> None:
    apt29 = seed_entity(db_session, "intrusion-set", "APT29", "Cozy Bear")
    before = _dictionary(db_session).version

    db_session.add(
        EntityAlias(
            entity_id=apt29.id,
            entity_type="intrusion-set",
            alias="Midnight Blizzard",
            alias_norm=alias_norm("Midnight Blizzard"),
            source="galaxy",
        )
    )
    db_session.flush()

    after = _dictionary(db_session)
    assert after.version != before
    assert after.entries["midnight blizzard"].canonical == "APT29"


def test_dictionary_skips_names_known_only_from_legacy_or_ransomware(db_session: Session) -> None:
    """Dev 2026-11-01: grup ransomware "Payload" (entitas legacy) masuk kamus dan cocok dengan
    kata biasa "payload" di artikel malware. Kamus hanya dari ATT&CK, Galaxy, analis, dan nama
    `threat_actor_groups`; nama legacy/dictionary di luar itu tidak dicocokkan."""
    seed_entity(db_session, "intrusion-set", "Payload", source="legacy")
    ransom = seed_entity(db_session, "intrusion-set", "Qilin", source="legacy")
    seed_entity(db_session, "intrusion-set", "Watched Crew", source="analyst")
    db_session.add(
        EntityAlias(
            entity_id=ransom.id,
            entity_type="intrusion-set",
            alias="Agenda",
            alias_norm=alias_norm("Agenda"),
            source="galaxy",
        )
    )
    db_session.execute(text("INSERT INTO threat_actor_groups (name, source) VALUES ('qilin', 'x')"))
    db_session.flush()

    entries = _dictionary(db_session).entries

    assert "payload" not in entries
    assert entries["qilin"].canonical == "Qilin"  # juga nama threat_actor_groups
    assert entries["agenda"].canonical == "Qilin"  # alias Galaxy
    assert entries["watched crew"].canonical == "Watched Crew"  # alias analis


def test_dictionary_version_changes_with_merge(db_session: Session) -> None:
    apt29 = seed_entity(db_session, "intrusion-set", "APT29")
    other = seed_entity(db_session, "intrusion-set", "Dark Halo", alias_source="galaxy")
    before = _dictionary(db_session)
    assert before.entries["dark halo"].canonical == "Dark Halo"

    # merge: alias pindah ke target, sumber jadi tombstone -> key sama, kanonik berubah
    db_session.execute(
        text("UPDATE entity_aliases SET entity_id = :t WHERE entity_id = :o"),
        {"t": apt29.id, "o": other.id},
    )
    other.merged_into_id = apt29.id
    db_session.flush()

    after = _dictionary(db_session)
    assert set(after.entries) == set(before.entries)
    assert after.entries["dark halo"].canonical == "APT29"
    assert after.version != before.version


def test_dictionary_rules_for_galaxy_suppressed_and_leftover_names(db_session: Session) -> None:
    apt28 = seed_entity(db_session, "intrusion-set", "APT28", "Sofacy")
    for alias in ("Grizzlysteppe", "Fancy Bear"):
        db_session.add(
            EntityAlias(
                entity_id=apt28.id,
                entity_type="intrusion-set",
                alias=alias,
                alias_norm=alias_norm(alias),
                source="galaxy",
            )
        )
    hidden = seed_entity(db_session, "intrusion-set", "Testactor", source="legacy")
    hidden.suppressed = True
    seed_entity(db_session, "tool", "Mimikatz")
    db_session.execute(
        text(
            "INSERT INTO threat_actor_groups (name, source) VALUES"
            " ('Leftovergang', 'manual'), ('testactor', 'manual'), ('mimikatz', 'manual')"
        )
    )
    db_session.flush()

    entries = _dictionary(db_session).entries

    assert entries["sofacy"].needs_context is False  # ATT&CK: hanya AMBIGUOUS
    assert entries["grizzlysteppe"].needs_context is True  # Ruling 23: satu kata Galaxy
    assert entries["fancy bear"].needs_context is False
    assert entries["leftovergang"].canonical == "Leftovergang"
    assert entries["leftovergang"].needs_context is True
    assert "testactor" not in entries  # suppressed tidak pernah dicocokkan
    assert entries["mimikatz"].kind == "tool"  # nama TA yang juga software tetap software


def test_ransomware_sink_creates_relationships(db_session: Session) -> None:
    repo = RansomwareVictimRepo(db_session)
    fields = {
        "group_name": "lockbit3",
        "victim": "Acme Widgets",
        "country_code": "us",
        "industry": "Finance & Insurance",
        "discovered": datetime.date(2026, 10, 3),
    }
    repo.upsert(offset_key="k1", **fields)
    repo.upsert(offset_key="k1", **{**fields, "discovered": datetime.date(2026, 10, 7)})

    rows = db_session.execute(
        text(
            "SELECT r.relationship_type, s.type, s.name, t.type, t.name, t.identity_class,"
            "       r.confidence, r.provenance, r.first_seen, r.last_seen"
            "  FROM relationships r JOIN entities s ON s.id = r.source_entity_id"
            "  JOIN entities t ON t.id = r.target_entity_id"
            " WHERE r.provenance = 'ransomware' ORDER BY r.relationship_type"
        )
    ).all()
    first = datetime.datetime(2026, 10, 3, tzinfo=_UTC)
    last = datetime.datetime(2026, 10, 7, tzinfo=_UTC)
    assert [tuple(r) for r in rows] == [
        ("located-at", "identity", "Acme Widgets", "location", "United States", None, 50,
         "ransomware", first, last),
        ("targets", "intrusion-set", "lockbit3", "identity", "Acme Widgets", "organization", 50,
         "ransomware", first, last),
    ]  # fmt: skip
    group = db_session.scalars(select(Entity).where(Entity.name == "lockbit3")).one()
    assert group.source == "ransomware"


def test_ransomware_victim_named_like_sector_is_not_linked(db_session: Session) -> None:
    RansomwareVictimRepo(db_session).upsert(
        offset_key="k2", group_name="qilin", victim="Healthcare", country_code="DE"
    )

    count = db_session.scalar(
        text("SELECT count(*) FROM relationships WHERE provenance = 'ransomware'")
    )
    assert count == 0  # Ruling 10: korban yang resolve ke sektor tidak ditautkan


def test_ransomware_relationship_stix_clash_gets_random_id(db_session: Session) -> None:
    """stix_id relasi uuid5 sudah dipakai relasi lain (relasi tetap di target sesudah split):
    upsert memakai id acak, bukan IntegrityError."""
    from cti_core.entity import relationship_stix_id
    from cti_core.entity.resolve import resolve

    group = resolve(db_session, "intrusion-set", "clashgroup", source="ransomware")
    victim = resolve(
        db_session, "identity", "Clash Victim", source="ransomware", identity_class="organization"
    )
    other = resolve(db_session, "intrusion-set", "othergroup", source="ransomware")
    clash = relationship_stix_id(group.stix_id, "targets", victim.stix_id)
    db_session.execute(
        text(
            "INSERT INTO relationships (stix_id, relationship_type, source_entity_id,"
            " target_entity_id, provenance) VALUES (:s, 'targets', :src, :dst, 'ransomware')"
        ),
        {"s": clash, "src": other.id, "dst": victim.id},
    )
    RansomwareVictimRepo(db_session).upsert(
        offset_key="k-clash", group_name="clashgroup", victim="Clash Victim"
    )
    stix = db_session.scalar(
        text(
            "SELECT stix_id FROM relationships WHERE source_entity_id = :g"
            " AND target_entity_id = :v AND relationship_type = 'targets'"
        ),
        {"g": group.id, "v": victim.id},
    )
    assert stix is not None and stix != clash and stix.startswith("relationship--")


def test_seed_fase10_writes_new_tables(db_session: Session) -> None:
    db_session.add(Client(client_id="sc", name="Sc"))
    db_session.flush()
    data = MemoryDump(
        {
            "threatintel/ta_profiles": [
                {"_actor_name": "apt36", "_generated_at": "2026-05-04T00:53:36+00:00", "x": 1}
            ],
            "threatintel/ta_watchlist": [{"name": "apt36", "client_id": "sc"}],
            "threatintel/whitelist": [{"name": "TestActor"}],
        }
    )

    for fn, key in (
        (seed.seed_ta_profiles, "threatintel/ta_profiles"),
        (seed.seed_ta_watchlist, "threatintel/ta_watchlist"),
        (seed.seed_ta_whitelist, "threatintel/whitelist"),
    ):
        assert fn(db_session, data.docs(key)).inserted == 1
        assert fn(db_session, data.docs(key)).existing == 1  # kedua kali: sudah ada

    apt36 = db_session.scalars(
        select(Entity).where(Entity.type == "intrusion-set", Entity.name == "apt36")
    ).one()
    profile = db_session.scalars(select(EntityProfile)).one()
    assert (profile.entity_id, profile.profile) == (apt36.id, {"x": 1})
    assert profile.generated_at == datetime.datetime(2026, 5, 4, 0, 53, 36, tzinfo=_UTC)
    watch = db_session.scalars(select(EntityWatch)).one()
    assert (watch.entity_id, watch.client_id) == (apt36.id, "sc")
    hidden = db_session.scalars(
        select(Entity).where(Entity.type == "intrusion-set", Entity.name == "TestActor")
    ).one()
    assert hidden.suppressed is True
