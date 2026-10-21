"""`tools/ops/replay_failed_enrichment` terhadap Postgres nyata: hanya baris GAGAL yang diambil
(bukan penolakan klasifikasi), status artikel per URL terbaca lewat join `url_hash`, dan penghapusan
stub "Manually Restored" tidak menyentuh artikel yang sudah diproses penuh."""

from __future__ import annotations

import datetime

from cti_core.db.models.article import Article
from cti_core.db.repositories.article import ArticleRepo, RejectedArticleRepo
from cti_core.urlkit import url_hash
from sqlalchemy import select
from sqlalchemy.orm import Session

from tools.ops.replay_failed_enrichment import STUB_NEWS_TYPE, delete_stubs, load_rows, plan

BASE = "https://replay.example/"


def seed(session: Session) -> None:
    rejected = RejectedArticleRepo(session)
    failed = "[enrichment_failed] X: boom"
    rejected.upsert(
        url=f"{BASE}new", title="New", source="A", reason=failed, failure_kind="permanent"
    )
    rejected.upsert(
        url=f"{BASE}stub", title="Stub", source="A", reason=failed, failure_kind="transient"
    )
    rejected.upsert(url=f"{BASE}live", title="Live", source="B", reason=failed, failure_kind="json")
    rejected.upsert(url=f"{BASE}cls", title="Not cyber", source="A", reason="vendor blog")
    articles = ArticleRepo(session)
    articles.upsert(url=f"{BASE}stub", title="Stub", source="A", news_type=STUB_NEWS_TYPE)
    articles.upsert(url=f"{BASE}live", title="Live", source="B", news_type="Global")
    session.flush()


def test_only_failed_rows_are_loaded_with_the_status_of_their_article(db_session: Session) -> None:
    seed(db_session)

    rows = {r.url: r for r in load_rows(db_session)}

    assert set(rows) == {f"{BASE}new", f"{BASE}stub", f"{BASE}live"}  # klasifikasi tidak ikut
    assert rows[f"{BASE}new"].article_news_type is None
    assert rows[f"{BASE}stub"].article_news_type == STUB_NEWS_TYPE
    assert rows[f"{BASE}live"].article_news_type == "Global"
    grouped = plan(rows.values())
    assert [r.title for r in grouped["enqueue"]] == ["New"]
    assert [r.title for r in grouped["stub_restored"]] == ["Stub"]
    assert [r.title for r in grouped["skip_article_exists"]] == ["Live"]


def test_filters_narrow_the_rows(db_session: Session) -> None:
    seed(db_session)

    assert [r.title for r in load_rows(db_session, kind="json")] == ["Live"]
    assert {r.title for r in load_rows(db_session, source="A")} == {"New", "Stub"}
    assert len(load_rows(db_session, limit=2)) == 2
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    assert load_rows(db_session, since=tomorrow) == []


def test_deleting_stubs_never_touches_a_fully_processed_article(db_session: Session) -> None:
    seed(db_session)
    rows = load_rows(db_session)

    removed = delete_stubs(db_session, plan(rows, replace_stubs=True)["replace_stub"])

    assert removed == 1
    hashes = [url_hash(f"{BASE}stub"), url_hash(f"{BASE}live")]
    left = {
        a.url_hash: a.news_type
        for a in db_session.scalars(select(Article).where(Article.url_hash.in_(hashes)))
    }
    assert left == {url_hash(f"{BASE}live"): "Global"}
