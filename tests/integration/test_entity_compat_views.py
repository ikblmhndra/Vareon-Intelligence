"""View kompatibilitas P7c-1 (spec 3.6): kode 0.8.2/0.8.10 yang di-rollback tetap bisa membaca DAN
menulis lewat nama tabel lama, yang kini view di atas `entity_mentions`/`entity_watches`/
`entity_profiles`/`entities`.

CI tidak bisa checkout tag, jadi kelas ORM 0.8.10 dibekukan di sini (salinan `git show
0.8.10:packages/cti-core/src/cti_core/db/models/{article,article_cve,ta}.py`) di `DeclarativeBase`
sendiri, dan test menjalankan operasi ORM yang sama dengan kode lama: tambah lewat relasi,
`pg_insert(...).on_conflict_do_nothing()`, delete-orphan, update profil. Stand-in `Article` cuma
memetakan `id` + relasi lama."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from cti_core.db.models.article import Article as CurrentArticle
from cti_core.db.models.auth import Client
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.indicator import Indicator
from cti_core.entity.resolve import resolve
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

# --- salinan beku ORM 0.8.10 ---------------------------------------------------------------


class _Base(DeclarativeBase):
    pass


class _TimestampMixin:
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class _Client(_Base):
    __tablename__ = "clients"
    client_id: Mapped[str] = mapped_column(String(50), primary_key=True)


class Article(_Base):
    __tablename__ = "articles"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    countries: Mapped[list[ArticleCountry]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="selectin"
    )
    industries: Mapped[list[ArticleIndustry]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="selectin"
    )
    threat_actors: Mapped[list[ArticleThreatActor]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="selectin"
    )
    ttps: Mapped[list[ArticleTTP]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="selectin"
    )
    malware: Mapped[list[ArticleMalware]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="selectin"
    )


class ArticleCountry(_Base):
    __tablename__ = "article_countries"
    __table_args__ = (
        UniqueConstraint("article_id", "country_code", "role", name="uq_article_country_role"),
        Index("ix_article_countries_country_role", "country_code", "role"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)

    article: Mapped[Article] = relationship(back_populates="countries")


class ArticleIndustry(_Base):
    __tablename__ = "article_industries"
    __table_args__ = (UniqueConstraint("article_id", "industry", name="uq_article_industry"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    industry: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="llm")

    article: Mapped[Article] = relationship(back_populates="industries")


class ArticleThreatActor(_Base):
    __tablename__ = "article_threat_actors"
    __table_args__ = (
        UniqueConstraint("article_id", "threat_actor", name="uq_article_threat_actor"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    threat_actor: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="dictionary")

    article: Mapped[Article] = relationship(back_populates="threat_actors")


class ArticleTTP(_Base):
    __tablename__ = "article_ttps"
    __table_args__ = (UniqueConstraint("article_id", "ttp_id", name="uq_article_ttp"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    ttp_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    ttp_name: Mapped[str] = mapped_column(String(300), nullable=False)
    extracted_id: Mapped[str | None] = mapped_column(String(50))
    extracted_name: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="llm")
    evidence: Mapped[str | None] = mapped_column(Text)

    article: Mapped[Article] = relationship(back_populates="ttps")


class ArticleMalware(_Base):
    __tablename__ = "article_malware"
    __table_args__ = (UniqueConstraint("article_id", "name", name="uq_article_malware"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="dictionary")

    article: Mapped[Article] = relationship(back_populates="malware")


class ArticleCve(_Base):
    __tablename__ = "article_cves"
    __table_args__ = (Index("ix_article_cves_cve_id", "cve_id"),)

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    cve_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    in_title: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TAWhitelistEntry(_Base):
    __tablename__ = "ta_whitelist"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    added_date: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TAWatchlistEntry(_TimestampMixin, _Base):
    __tablename__ = "ta_watchlist"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True
    )


class TAProfile(_Base):
    __tablename__ = "ta_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# --- helper -----------------------------------------------------------------------------------


def _article(s: Session, key: str) -> Article:
    a = CurrentArticle(
        url=f"https://cv.example/{key}", url_hash=f"cv-{key}", title="t", source="cv"
    )
    s.add(a)
    s.flush()
    s.expunge(a)
    return s.get_one(Article, a.id)


def _q(s: Session, sql: str, **params: object) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in s.execute(text(sql), params)]


def _mentions(s: Session, article_id: int) -> list[tuple[Any, ...]]:
    return _q(
        s,
        "SELECT m.id, e.type, e.name, m.matched_alias, m.method, m.role FROM entity_mentions m"
        " JOIN entities e ON e.id = m.entity_id WHERE m.article_id = :a ORDER BY m.id",
        a=article_id,
    )


def _actor(s: Session, name: str, *aliases: str) -> int:
    eid = resolve(s, "intrusion-set", name, source="analyst").id
    for a in aliases:
        s.execute(
            text(
                "INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)"
                " VALUES (:e, 'intrusion-set', CAST(:a AS text),"
                " entity_alias_norm(CAST(:a AS text)), 'analyst')"
            ),
            {"e": eid, "a": a},
        )
    return eid


def _fresh(s: Session, article_id: int) -> Article:
    s.expire_all()
    return s.get_one(Article, article_id)


# DELETE id fantom/ber-id-baru tidak menemukan baris view: SQLAlchemy hanya memperingatkan
_DELETE_UNMATCHED = pytest.mark.filterwarnings(
    "ignore:DELETE statement on table .* were matched:sqlalchemy.exc.SAWarning"
)

# --- test -------------------------------------------------------------------------------------


def test_old_orm_append_actor_via_relationship(db_session: Session) -> None:
    s = db_session
    apt29 = _actor(s, "APT29", "Cozy Bear")
    art = _article(s, "append")
    row = ArticleThreatActor(threat_actor="Cozy bear")  # source dari server_default
    art.threat_actors.append(row)
    s.flush()
    assert _mentions(s, art.id) == [
        (row.id, "intrusion-set", "APT29", "Cozy bear", "dictionary", None)
    ]
    assert row.source == "dictionary"  # RETURNING server_default terisi
    assert _q(s, "SELECT entity_id FROM entity_mentions WHERE id = :i", i=row.id) == [(apt29,)]
    # baca ulang lewat view: nama = nama entitas
    got = _fresh(s, art.id).threat_actors
    assert [(r.id, r.threat_actor, r.source) for r in got] == [(row.id, "APT29", "dictionary")]


def test_old_pg_insert_article_cves_on_conflict(db_session: Session) -> None:
    s = db_session
    art = _article(s, "cves")
    rows = [{"article_id": art.id, "cve_id": "CVE-2026-1234", "in_title": True}]
    s.execute(pg_insert(ArticleCve).values(rows).on_conflict_do_nothing())
    s.execute(pg_insert(ArticleCve).values(rows).on_conflict_do_nothing())  # replay idempoten
    assert [m[1:5] for m in _mentions(s, art.id)] == [
        ("vulnerability", "CVE-2026-1234", "CVE-2026-1234", "legacy")
    ]
    assert _q(
        s,
        "SELECT type, name, external_id FROM entities WHERE name = 'CVE-2026-1234'",
    ) == [("vulnerability", "CVE-2026-1234", "CVE-2026-1234")]
    view = _q(
        s,
        "SELECT cve_id, in_title, first_seen_at IS NOT NULL FROM article_cves"
        " WHERE article_id = :a",
        a=art.id,
    )
    assert view == [("CVE-2026-1234", True, True)]
    s.execute(text("DELETE FROM article_cves WHERE article_id = :a"), {"a": art.id})
    assert _mentions(s, art.id) == []


def test_old_insert_lowercase_cve_is_uppercased(db_session: Session) -> None:
    """CVE huruf kecil dari kode lama: entitas tetap `CVE-...` (sama dengan resolver Python)."""
    s = db_session
    art = _article(s, "cves-lower")
    rows = [{"article_id": art.id, "cve_id": "cve-2026-7777", "in_title": False}]
    s.execute(pg_insert(ArticleCve).values(rows).on_conflict_do_nothing())
    assert _q(
        s,
        "SELECT name, external_id FROM entities WHERE type = 'vulnerability'"
        " AND lower(name) = 'cve-2026-7777'",
    ) == [("CVE-2026-7777", "CVE-2026-7777")]
    view = _q(s, "SELECT cve_id FROM article_cves WHERE article_id = :a", a=art.id)
    assert view == [("CVE-2026-7777",)]


def test_old_insert_cve_named_by_analyst_does_not_fail(db_session: Session) -> None:
    """Entitas analis "Log4Shell" sudah memegang external_id CVE: insert lama tidak boleh error."""
    s = db_session
    s.execute(
        text(
            "INSERT INTO entities (type, stix_id, name, source, external_id) VALUES"
            " ('vulnerability', 'vulnerability--l4s-compat', 'Log4Shell C', 'analyst',"
            " 'CVE-2026-8888')"
        )
    )
    art = _article(s, "cves-named")
    rows = [{"article_id": art.id, "cve_id": "CVE-2026-8888", "in_title": False}]
    s.execute(pg_insert(ArticleCve).values(rows).on_conflict_do_nothing())
    assert len(_mentions(s, art.id)) == 1


def test_old_delete_orphan_removes_mention(db_session: Session) -> None:
    s = db_session
    _actor(s, "APT28")
    art = _article(s, "orphan")
    art.threat_actors.append(ArticleThreatActor(threat_actor="APT28", source="dictionary"))
    art.malware.append(ArticleMalware(name="Emotet", kind="malware"))
    s.flush()
    assert len(_mentions(s, art.id)) == 2
    art.threat_actors.clear()
    art.malware = []
    s.flush()
    assert _mentions(s, art.id) == []


@_DELETE_UNMATCHED  # DELETE baris lama yang id-nya sudah diganti
def test_old_reconcile_alias_keeps_mention(db_session: Session) -> None:
    """`_reconcile` 0.8.10: baris lama (dibaca dengan nama entitas) tidak ada di daftar baru, ejaan
    alias baru ditambah. UoW menjalankan INSERT sebelum DELETE: mention harus tetap ada."""
    s = db_session
    _actor(s, "APT29", "Cozy Bear")
    art = _article(s, "reconcile")
    art.threat_actors.append(ArticleThreatActor(threat_actor="APT29"))
    s.flush()
    art = _fresh(s, art.id)
    art.threat_actors = [ArticleThreatActor(threat_actor="Cozy Bear")]
    s.flush()
    assert [m[1:4] for m in _mentions(s, art.id)] == [("intrusion-set", "APT29", "APT29")]
    assert [r.threat_actor for r in _fresh(s, art.id).threat_actors] == ["APT29"]


def test_old_ttp_resolves_by_technique_id_and_updates(db_session: Session) -> None:
    s = db_session
    tid = s.execute(
        text("SELECT entity_resolve_technique('T1566.001', 'Spearphishing Attachment', 'attack')")
    ).scalar_one()
    art = _article(s, "ttp")
    row = ArticleTTP(
        ttp_id="T1566.001",
        ttp_name="Some LLM Name",  # nama tidak dipakai untuk identitas (Ruling 7)
        extracted_id="T1193",
        extracted_name="Spearphish",
        evidence="lure",
    )
    art.ttps.append(row)
    s.flush()
    assert row.source == "llm"
    got = _q(
        s,
        "SELECT entity_id, matched_alias, method, evidence, extracted FROM entity_mentions"
        " WHERE id = :i",
        i=row.id,
    )
    assert got == [
        (
            tid,
            "T1566.001",
            "llm",
            "lure",
            {"extracted_id": "T1193", "extracted_name": "Spearphish"},
        )
    ]
    # apply_ttps 0.8.10 memperbarui baris yang dipakai ulang
    row = _fresh(s, art.id).ttps[0]
    assert (row.ttp_id, row.ttp_name) == ("T1566.001", "Spearphishing Attachment")
    row.source = "explicit"
    row.evidence = "new"
    row.extracted_id = None
    s.flush()
    got = _q(s, "SELECT method, evidence, extracted FROM entity_mentions WHERE id = :i", i=row.id)
    assert got == [("explicit", "new", {"extracted_name": "Spearphish"})]


def test_old_malware_kind_and_industry_source_update(db_session: Session) -> None:
    s = db_session
    art = _article(s, "upd")
    mal = ArticleMalware(name="Cobalt Strike", kind="malware")
    ind = ArticleIndustry(industry="Finance & Insurance")
    art.malware.append(mal)
    art.industries.append(ind)
    s.flush()
    mal.kind = "tool"  # _apply_enrichment: kind baris pakai-ulang ikut diperbarui
    ind.source = "keyword"
    s.flush()
    assert sorted(m[1:5] for m in _mentions(s, art.id)) == [
        ("identity", "Financial Services", "Finance & Insurance", "keyword"),
        ("tool", "Cobalt Strike", "Cobalt Strike", "dictionary"),
    ]


def test_old_profile_update(db_session: Session) -> None:
    s = db_session
    eid = _actor(s, "Shinyhunters", "Shiny Hunters")
    p = TAProfile(actor_name="Shiny Hunters", profile={"v": 1})
    s.add(p)
    s.flush()
    assert p.generated_at is not None
    assert _q(
        s, "SELECT id, entity_id, profile FROM entity_profiles WHERE entity_id = :e", e=eid
    ) == [(p.id, eid, {"v": 1})]
    p.profile = {"v": 2}
    p.generated_at = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    s.flush()
    assert _q(s, "SELECT profile, generated_at FROM entity_profiles WHERE id = :i", i=p.id) == [
        ({"v": 2}, datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    ]
    # INSERT kedua untuk aktor yang sama (ejaan lain) = upsert, bukan baris kedua
    s.expunge(p)
    q = TAProfile(actor_name="shinyhunters", profile={"v": 3})
    s.add(q)
    s.flush()
    assert q.id == p.id
    assert _q(s, "SELECT profile FROM entity_profiles WHERE entity_id = :e", e=eid) == [({"v": 3},)]
    s.delete(q)
    s.flush()
    assert _q(s, "SELECT count(*) FROM entity_profiles WHERE entity_id = :e", e=eid) == [(0,)]


def test_old_watchlist_add_remove(db_session: Session) -> None:
    s = db_session
    s.merge(Client(client_id="cvc", name="CV"))
    eid = _actor(s, "APT29", "Cozy Bear")
    w = TAWatchlistEntry(name="Cozy Bear", client_id="cvc")
    s.add(w)
    s.flush()
    assert w.created_at is not None and w.updated_at is not None
    assert _q(s, "SELECT id, entity_id FROM entity_watches WHERE client_id = 'cvc'") == [
        (w.id, eid)
    ]
    assert _q(s, "SELECT name FROM ta_watchlist WHERE id = :i", i=w.id) == [("APT29",)]
    s.delete(w)
    s.flush()
    assert _q(s, "SELECT count(*) FROM entity_watches WHERE client_id = 'cvc'") == [(0,)]


def test_old_whitelist_add_suppresses(db_session: Session) -> None:
    s = db_session
    eid = _actor(s, "Testactor")
    w = TAWhitelistEntry(name="testactor")
    s.add(w)
    s.flush()
    assert w.id == eid and w.added_date is not None
    assert _q(s, "SELECT suppressed FROM entities WHERE id = :e", e=eid) == [(True,)]
    assert _q(s, "SELECT name FROM ta_whitelist WHERE id = :e", e=eid) == [("testactor",)]
    s.delete(w)
    s.flush()
    assert _q(s, "SELECT suppressed FROM entities WHERE id = :e", e=eid) == [(False,)]


@_DELETE_UNMATCHED  # DELETE id fantom
def test_suppressed_name_insert_is_dropped(db_session: Session) -> None:
    """Review Focus 5: nama entitas suppressed -> tanpa mention, tanpa error, artikel jalan."""
    s = db_session
    eid = _actor(s, "Noisy Group")
    s.execute(text("UPDATE entities SET suppressed = true WHERE id = :e"), {"e": eid})
    art = _article(s, "suppressed")
    row = ArticleThreatActor(threat_actor="noisy group")
    art.threat_actors.append(row)
    art.threat_actors.append(ArticleThreatActor(threat_actor="Quiet Group"))
    art.industries.append(ArticleIndustry(industry="General"))  # "General" juga dibuang
    s.flush()
    assert row.id is not None
    assert [m[2] for m in _mentions(s, art.id)] == ["Quiet Group"]
    art.threat_actors.clear()  # DELETE id fantom: tetap mulus
    s.flush()


def test_industry_view_returns_original_label(db_session: Session) -> None:
    s = db_session
    art = _article(s, "industry")
    art.industries.append(ArticleIndustry(industry="Cloud Services"))
    art.industries.append(ArticleIndustry(industry="Underwater Basketry"))
    s.flush()
    labels = sorted(r.industry for r in _fresh(s, art.id).industries)
    assert labels == ["Cloud Services", "Underwater Basketry"]
    assert sorted(m[2] for m in _mentions(s, art.id)) == ["Technology", "Underwater Basketry"]
    assert _q(
        s, "SELECT source, identity_class FROM entities WHERE name = 'Underwater Basketry'"
    ) == [("legacy", "class")]


def test_old_country_lookup_by_code(db_session: Session) -> None:
    s = db_session
    art = _article(s, "country")
    rows = [
        ArticleCountry(country_code="us", role="victim"),
        ArticleCountry(country_code="US", role="actor"),
        ArticleCountry(country_code="QQ", role="victim"),
    ]
    art.countries.extend(rows)
    s.flush()  # satu flush multi-baris: id RETURNING harus cocok per baris
    assert [r.id for r in rows] == [m[0] for m in _mentions(s, art.id)]
    assert [m[1:6] for m in _mentions(s, art.id)] == [
        ("location", "United States", "us", "legacy", "victim"),
        ("location", "United States", "US", "legacy", "actor"),
        ("location", "QQ", "QQ", "legacy", "victim"),
    ]
    got = sorted((c.country_code, c.role) for c in _fresh(s, art.id).countries)
    assert got == [("QQ", "victim"), ("US", "actor"), ("US", "victim")]


def test_indicator_and_cve_views_writable_for_old_code(db_session: Session) -> None:
    """0.8.10 menulis `ioc_threat_actors` (view P7a di atas `indicator_threat_actors`) dan
    menghapus `cve_tracker` lewat cascade ORM ke `cve_threat_actors`/`cve_ttps`."""
    s = db_session
    s.merge(Client(client_id="cvc", name="CV"))
    ind = Indicator(type="ip", value="192.0.2.77")
    cve = CveTracker(cve_id="CVE-2026-7777", client_id="cvc", tech="x")
    s.add_all([ind, cve])
    s.flush()
    iid = s.execute(
        text(
            "INSERT INTO ioc_threat_actors (ioc_id, threat_actor) VALUES (:i, 'APT28') RETURNING id"
        ),
        {"i": ind.id},
    ).scalar_one()
    assert _q(s, "SELECT threat_actor FROM indicator_threat_actors WHERE id = :i", i=iid) == [
        ("APT28",)
    ]
    for sql in (
        "INSERT INTO cve_threat_actors (cve_tracker_id, threat_actor) VALUES (:c, 'APT28')",
        "INSERT INTO cve_ttps (cve_tracker_id, ttp_id, ttp_name) VALUES (:c, 't1566', 'x')",
    ):
        s.execute(text(sql), {"c": cve.id})
    assert _q(s, "SELECT ttp_id FROM cve_ttps WHERE cve_tracker_id = :c", c=cve.id) == [("T1566",)]
    s.execute(text("DELETE FROM ioc_threat_actors WHERE id = :i"), {"i": iid})
    s.execute(text("DELETE FROM cve_threat_actors WHERE cve_tracker_id = :c"), {"c": cve.id})
    s.execute(text("DELETE FROM cve_ttps WHERE cve_tracker_id = :c"), {"c": cve.id})
    assert _q(
        s,
        "SELECT count(*) FROM entity_mentions WHERE indicator_id = :i OR cve_tracker_id = :c",
        i=ind.id,
        c=cve.id,
    ) == [(0,)]


def test_views_without_trigger_reject_writes(db_session: Session) -> None:
    """UPDATE pada view yang tidak pernah di-UPDATE kode lama tetap ditolak (tanpa trigger)."""
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(text("UPDATE article_countries SET role = 'actor'"))


def test_old_and_new_writes_same_entity(db_session: Session) -> None:
    s = db_session
    art = _article(s, "same")
    row = ArticleThreatActor(threat_actor="Cozy bear")
    art.threat_actors.append(row)
    s.flush()
    old_entity = _q(s, "SELECT entity_id FROM entity_mentions WHERE id = :i", i=row.id)[0][0]
    assert resolve(s, "intrusion-set", "COZY  BEAR", source="dictionary").id == old_entity


def test_legacy_tables_kept(db_session: Session) -> None:
    names = {
        r[0]
        for r in _q(
            db_session,
            "SELECT relname FROM pg_class"
            " WHERE relname LIKE '\\_legacy\\_%' AND relkind IN ('r', 'S')",
        )
    }
    assert "_legacy_article_threat_actors" in names
    assert "_legacy_article_cves" in names
    assert "_legacy_article_threat_actors_id_seq" in names


def test_update_to_blank_general_or_suppressed_deletes_mention(db_session: Session) -> None:
    """UPDATE yang mengganti kunci ke nama tanpa entitas ("General") atau ke entitas suppressed
    menghapus mention, sama dengan INSERT yang dibuang."""
    s = db_session
    eid = _actor(s, "Muted Crew")
    s.execute(text("UPDATE entities SET suppressed = true WHERE id = :e"), {"e": eid})
    art = _article(s, "repoint")
    ind = ArticleIndustry(industry="Finance & Insurance")
    actor = ArticleThreatActor(threat_actor="APT41")
    art.industries.append(ind)
    art.threat_actors.append(actor)
    s.flush()
    assert len(_mentions(s, art.id)) == 2
    ind.industry = "General"
    actor.threat_actor = "muted crew"
    s.flush()
    assert _mentions(s, art.id) == []


def test_ta_views_blank_name_is_phantom(db_session: Session) -> None:
    s = db_session
    s.merge(Client(client_id="cvc", name="CV"))
    rows = [
        TAWatchlistEntry(name="   ", client_id="cvc"),
        TAProfile(actor_name="", profile={"v": 1}),
        TAWhitelistEntry(name=" "),
    ]
    s.add_all(rows)
    s.flush()
    assert all(r.id is not None for r in rows)
    assert _q(
        s,
        "SELECT (SELECT count(*) FROM entity_watches WHERE client_id = 'cvc'),"
        " (SELECT count(*) FROM entity_profiles WHERE id = :p),"
        " (SELECT count(*) FROM entities WHERE name = '')",
        p=rows[1].id,
    ) == [(0, 0, 0)]
