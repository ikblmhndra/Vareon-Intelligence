"""`cti_enrich.story_backfill` -- Postgres REAL (testcontainers)."""

from __future__ import annotations

import datetime as dt

from cti_core.db.models.article import Article
from cti_core.db.models.story import Story
from cti_core.db.repositories.article import ArticleRepo
from cti_core.db.repositories.article_cve import ArticleCveRepo
from cti_enrich.story_backfill import backfill
from sqlalchemy import func, select
from sqlalchemy.orm import Session

T0 = dt.datetime(2026, 10, 1, 8, 0, tzinfo=dt.UTC)


def _seed(session: Session) -> list[int]:
    """A dan B berbagi CVE dari sumber beda; C tidak berhubungan."""
    spec = [
        ("Zero-day CVE-2026-9001 exploited in the wild", "SrcA", {"CVE-2026-9001"}),
        ("Attackers abuse flaw CVE-2026-9001 to breach firms", "SrcB", {"CVE-2026-9001"}),
        ("Quarterly gardening tips for spring", "SrcC", set()),
    ]
    ids = []
    for n, (title, source, cves) in enumerate(spec):
        article = ArticleRepo(session).upsert(
            url=f"https://example.com/backfill-{n}", title=title, source=source
        )
        article.first_seen_at = T0 + dt.timedelta(hours=n)
        session.flush()
        ArticleCveRepo(session).add_many(article.id, cves, title)
        ids.append(article.id)
    return ids


def test_backfill_groups_articles_and_is_idempotent(db_session: Session) -> None:
    ids = _seed(db_session)

    report = backfill(db_session, since=None, dry_run=False)

    assert (report.stories, report.followups) == (2, 1)
    assert report.top[0][1] == 2
    rows = {
        a.id: (a.story_id, a.story_match)
        for a in db_session.execute(select(Article).where(Article.id.in_(ids))).scalars()
    }
    assert rows[ids[0]][1] == "lead"
    assert rows[ids[1]] == (rows[ids[0]][0], "cve")
    assert rows[ids[2]][0] != rows[ids[0]][0]
    story = db_session.get(Story, rows[ids[0]][0])
    assert story is not None
    db_session.refresh(story)
    assert (story.article_count, story.source_count, story.classify) == (2, 2, None)
    assert story.lead_article_id == ids[0]

    before = db_session.scalar(select(func.count()).select_from(Story))
    again = backfill(db_session, since=None, dry_run=False)
    assert (again.stories, again.followups, again.top) == (0, 0, [])
    assert db_session.scalar(select(func.count()).select_from(Story)) == before


def test_dry_run_reports_but_leaves_no_rows(db_session: Session) -> None:
    ids = _seed(db_session)

    report = backfill(db_session, since=None, dry_run=True)

    assert (report.stories, report.followups) == (2, 1)
    assert db_session.scalar(select(func.count()).select_from(Story)) == 0
    stored = db_session.execute(select(Article.story_id).where(Article.id.in_(ids))).scalars().all()
    assert stored == [None, None, None]


def test_since_skips_older_articles(db_session: Session) -> None:
    _seed(db_session)

    report = backfill(db_session, since=dt.date(2026, 10, 2), dry_run=True)

    assert report.stories + report.followups == 0
