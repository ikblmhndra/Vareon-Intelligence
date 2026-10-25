"""`cti_enrich.canonicalise_actors` di Postgres beneran: alias -> nama kanonik di artikel,
watchlist, profil TA dan kriteria PIR; duplikat digabung; dry-run tidak menulis."""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import pytest
from cti_core.db.models.article import Article, ArticleThreatActor
from cti_core.db.models.attack import AttackGroup
from cti_core.db.models.auth import Client
from cti_core.db.models.pir import PIRRequirement
from cti_core.db.models.ta import TAProfile, TAWatchlistEntry
from cti_core.db.repositories.article import ArticleRepo
from cti_enrich.canonicalise_actors import canonicalise_actors
from sqlalchemy import select
from sqlalchemy.orm import Session

CLIENT = "canon-client"


@pytest.fixture
def session(_migrated_schema: None) -> Iterator[Session]:
    """`create_savepoint`: commit/rollback milik perintah hanya menyentuh SAVEPOINT, transaksi
    luar di-rollback saat teardown."""
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


@pytest.fixture
def seeded(session: Session) -> Session:
    # Nama grup sengaja unik supaya tidak bentrok dengan data ATT&CK lain di DB test.
    session.add(
        AttackGroup(
            stix_id="intrusion-set--test-canon",
            group_id="G9077",
            name="Canonwolf",
            aliases=["Canonwolf", "Paper Heron", "Glass Owl"],
        )
    )
    session.add(Client(client_id=CLIENT, name="Canon"))
    session.flush()
    return session


def _article(session: Session, n: int, actors: list[str]) -> Article:
    art = ArticleRepo(session).upsert(
        url=f"https://example.com/canon-{n}", title=f"Canon story {n}", source="s"
    )
    ArticleRepo(session).set_enrichment(art, threat_actors=actors)
    return art


def _actors(session: Session, art: Article) -> list[str]:
    return sorted(
        session.execute(
            select(ArticleThreatActor.threat_actor).where(ArticleThreatActor.article_id == art.id)
        ).scalars()
    )


def test_article_alias_renamed(seeded: Session) -> None:
    art = _article(seeded, 1, ["Paper heron", "Shinyhunters"])
    seeded.commit()

    stats = canonicalise_actors(seeded, dry_run=False)

    assert _actors(seeded, art) == ["Canonwolf", "Shinyhunters"]
    assert stats.articles.renamed[("Paper heron", "Canonwolf")] == 1


def test_article_alias_merged_into_existing_canonical(seeded: Session) -> None:
    both = _article(seeded, 2, ["Paper heron", "Canonwolf"])
    two_aliases = _article(seeded, 3, ["Paper heron", "Glass owl"])
    seeded.commit()

    stats = canonicalise_actors(seeded, dry_run=False)

    assert _actors(seeded, both) == ["Canonwolf"]
    assert _actors(seeded, two_aliases) == ["Canonwolf"]
    assert stats.articles.merged[("Paper heron", "Canonwolf")] == 1
    assert sum(stats.articles.renamed.values()) + sum(stats.articles.merged.values()) == 3


def test_dry_run_writes_nothing(seeded: Session) -> None:
    art = _article(seeded, 4, ["Paper heron"])
    seeded.add(TAWatchlistEntry(name="paper heron", client_id=CLIENT))
    seeded.commit()

    stats = canonicalise_actors(seeded, dry_run=True)

    assert stats.articles.renamed[("Paper heron", "Canonwolf")] == 1
    assert stats.watchlist.renamed[("paper heron", "Canonwolf")] == 1
    assert _actors(seeded, art) == ["Paper heron"]
    assert seeded.execute(
        select(TAWatchlistEntry.name).where(TAWatchlistEntry.client_id == CLIENT)
    ).scalars().all() == ["paper heron"]


def test_watchlist_renamed_or_dropped_when_canonical_present(seeded: Session) -> None:
    seeded.add(Client(client_id="canon-other", name="Other"))
    seeded.flush()
    seeded.add_all(
        [
            TAWatchlistEntry(name="paper heron", client_id=CLIENT),
            TAWatchlistEntry(name="canonwolf", client_id=CLIENT),
            TAWatchlistEntry(name="glass owl", client_id="canon-other"),
        ]
    )
    seeded.commit()

    stats = canonicalise_actors(seeded, dry_run=False)

    rows = seeded.execute(
        select(TAWatchlistEntry.client_id, TAWatchlistEntry.name)
        .where(TAWatchlistEntry.client_id.in_([CLIENT, "canon-other"]))
        .order_by(TAWatchlistEntry.client_id, TAWatchlistEntry.name)
    ).all()
    assert [tuple(r) for r in rows] == [("canon-client", "canonwolf"), ("canon-other", "Canonwolf")]
    assert stats.watchlist.merged[("paper heron", "Canonwolf")] == 1
    assert stats.watchlist.renamed[("glass owl", "Canonwolf")] == 1


def test_profile_conflict_keeps_newest(seeded: Session) -> None:
    old = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    new = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)
    seeded.add_all(
        [
            TAProfile(actor_name="Canonwolf", profile={"v": "old"}, generated_at=old),
            TAProfile(actor_name="paper heron", profile={"v": "new"}, generated_at=new),
            TAProfile(actor_name="glass owl", profile={"v": "older"}, generated_at=old),
        ]
    )
    seeded.commit()

    stats = canonicalise_actors(seeded, dry_run=False)

    profiles = seeded.execute(
        select(TAProfile.actor_name, TAProfile.profile).where(
            TAProfile.actor_name.in_(["Canonwolf", "paper heron", "glass owl"])
        )
    ).all()
    assert [tuple(p) for p in profiles] == [("Canonwolf", {"v": "new"})]
    assert sorted(stats.dropped_profiles) == ["Canonwolf", "glass owl"]


def test_pir_criteria_rewritten(seeded: Session) -> None:
    pir = PIRRequirement(
        title="Canon PIR",
        client_id=CLIENT,
        criteria={"threat_actors": ["Paper heron", "Canonwolf", "Shinyhunters"], "ttps": ["T1566"]},
    )
    seeded.add(pir)
    seeded.commit()

    stats = canonicalise_actors(seeded, dry_run=False)

    seeded.refresh(pir)
    assert pir.criteria == {"threat_actors": ["Canonwolf", "Shinyhunters"], "ttps": ["T1566"]}
    assert stats.pir.merged[("Paper heron", "Canonwolf")] == 1


def test_second_run_changes_nothing(seeded: Session) -> None:
    _article(seeded, 5, ["Glass owl"])
    seeded.commit()
    canonicalise_actors(seeded, dry_run=False)

    again = canonicalise_actors(seeded, dry_run=False)

    assert not again.articles.renamed and not again.articles.merged
