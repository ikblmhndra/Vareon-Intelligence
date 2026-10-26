"""Kolom `source`/`evidence` Tier 1 + `article_malware` -- Postgres REAL (testcontainers)."""

from __future__ import annotations

import pytest
from cti_core.attack_ttp import NormalizedTTP
from cti_core.db.models.article import Article
from cti_core.db.repositories.article import ArticleRepo
from sqlalchemy import text
from sqlalchemy.orm import Session


def _article(session: Session, suffix: str = "a") -> tuple[ArticleRepo, Article]:
    repo = ArticleRepo(session)
    art = repo.upsert(url=f"https://example.com/tier1-{suffix}", title="T", source="s")
    return repo, art


def test_set_enrichment_writes_sources(db_session: Session) -> None:
    repo, art = _article(db_session)
    repo.set_enrichment(
        art,
        industries=["Finance"],
        threat_actors=["APT29"],
        ttps=[
            NormalizedTTP(
                "T1190",
                "Exploit Public-Facing Application",
                source="explicit",
                evidence="exploited T1190",
            ),
            NormalizedTTP("T1486", "Data Encrypted for Impact", source="keyword"),
            ("T1566", "Phishing"),
        ],
        malware=[("LockBit", "malware"), ("Cobalt Strike", "tool")],
        industry_source="keyword",
    )
    db_session.refresh(art)
    ttps = {t.ttp_id: (t.source, t.evidence) for t in art.ttps}
    assert ttps == {
        "T1190": ("explicit", "exploited T1190"),
        "T1486": ("keyword", None),
        "T1566": ("llm", None),
    }
    assert {(m.name, m.kind, m.source) for m in art.malware} == {
        ("LockBit", "malware", "dictionary"),
        ("Cobalt Strike", "tool", "dictionary"),
    }
    assert [i.source for i in art.industries] == ["keyword"]
    assert [a.source for a in art.threat_actors] == ["dictionary"]


def test_invalid_source_rejected(db_session: Session) -> None:
    repo, art = _article(db_session, "bad")
    with pytest.raises(ValueError):
        repo.set_enrichment(art, ttps=[NormalizedTTP("T1190", "x", source="bogus")])
    with pytest.raises(ValueError):
        repo.set_enrichment(art, malware=[("X", "virus")])
    with pytest.raises(ValueError):
        repo.set_enrichment(art, industries=["Finance"], industry_source="bogus")


def test_add_tier1_is_add_only(db_session: Session) -> None:
    repo, art = _article(db_session, "addonly")
    repo.set_enrichment(
        art,
        industries=["General"],
        ttps=[NormalizedTTP("T1190", "Exploit Public-Facing Application", source="llm")],
    )
    counts = repo.add_tier1(
        art,
        ttps=[
            NormalizedTTP("T1190", "Exploit Public-Facing Application", source="keyword"),
            NormalizedTTP("T1486", "Data Encrypted for Impact", source="keyword"),
        ],
        threat_actors=["APT29"],
        malware=[("LockBit", "malware")],
        industries=["Finance"],
    )
    assert counts == {"ttps": 1, "threat_actors": 1, "malware": 1, "industries": 1}
    db_session.refresh(art)
    assert {(t.ttp_id, t.source) for t in art.ttps} == {("T1190", "llm"), ("T1486", "keyword")}
    assert [(i.industry, i.source) for i in art.industries] == [("Finance", "keyword")]

    # industri spesifik dari LLM dipertahankan: tidak ditambah
    repo2, art2 = _article(db_session, "specific")
    repo2.set_enrichment(art2, industries=["Healthcare"])
    counts2 = repo2.add_tier1(art2, ttps=[], threat_actors=[], malware=[], industries=["Finance"])
    assert counts2["industries"] == 0
    db_session.refresh(art2)
    assert [i.industry for i in art2.industries] == ["Healthcare"]


def test_existing_rows_default_sources(db_session: Session) -> None:
    _, art = _article(db_session, "defaults")
    db_session.execute(
        text("INSERT INTO article_ttps (article_id, ttp_id, ttp_name) VALUES (:a, 'T1', 'n')"),
        {"a": art.id},
    )
    db_session.execute(
        text("INSERT INTO article_threat_actors (article_id, threat_actor) VALUES (:a, 'X')"),
        {"a": art.id},
    )
    db_session.execute(
        text("INSERT INTO article_industries (article_id, industry) VALUES (:a, 'Finance')"),
        {"a": art.id},
    )
    db_session.expire_all()
    assert [t.source for t in art.ttps] == ["llm"]
    assert [a.source for a in art.threat_actors] == ["dictionary"]
    assert [i.source for i in art.industries] == ["llm"]


def test_remap_keeps_tier1_source_and_evidence(db_session: Session) -> None:
    from cti_core.db.repositories.ttp_catalog import load_catalog, remap_article_ttps

    from tests.integration.test_ttp_normalization import _catalog_rows

    db_session.add_all(_catalog_rows())
    db_session.flush()
    repo, art = _article(db_session, "remap")
    # (T1110, "Credential Dumping") di-remap ke T1003; dua baris lama menyatu ke satu ID
    # (T1110 salah-pasang) -> sumber terkuat (explicit) dan buktinya yang dipertahankan.
    repo.set_enrichment(
        art,
        ttps=[
            NormalizedTTP("T1110", "Credential Dumping", source="explicit", evidence="bukti"),
            NormalizedTTP("T1548", "Abuse Elevation Control Mechanism", source="keyword"),
        ],
    )
    article_id = art.id
    remap_article_ttps(db_session, load_catalog(db_session))
    art = db_session.get_one(Article, article_id)
    got = {t.ttp_id: (t.source, t.evidence) for t in art.ttps}
    assert got["T1003"] == ("explicit", "bukti")
    assert got["T1548"] == ("keyword", None)


def test_malware_same_name_different_kind(db_session: Session) -> None:
    repo, art = _article(db_session, "malkind")
    repo.set_enrichment(art, malware=[("Mimikatz", "tool"), ("Mimikatz", "malware")])
    db_session.refresh(art)
    assert [(m.name, m.kind) for m in art.malware] == [("Mimikatz", "tool")]
    repo.set_enrichment(art, malware=[("Mimikatz", "malware")])
    db_session.refresh(art)
    assert [(m.name, m.kind) for m in art.malware] == [("Mimikatz", "malware")]


def test_reenrichment_updates_reused_rows(db_session: Session) -> None:
    repo, art = _article(db_session, "reuse")
    repo.set_enrichment(art, industries=["Finance"], ttps=[("T1190", "Exploit")])
    repo.set_enrichment(
        art,
        industries=["Finance"],
        industry_source="keyword",
        ttps=[NormalizedTTP("T1190", "Exploit", source="explicit", evidence="e")],
    )
    db_session.refresh(art)
    assert [(t.source, t.evidence) for t in art.ttps] == [("explicit", "e")]
    assert [i.source for i in art.industries] == ["keyword"]
