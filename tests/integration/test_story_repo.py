"""`stories` + `StoryRepo` -- Postgres REAL (testcontainers)."""

from __future__ import annotations

import datetime as dt
import threading

import pytest
from cti_core.db.engine import sync_session
from cti_core.db.models.article import Article
from cti_core.db.models.story import Story
from cti_core.db.repositories.article import ArticleRepo, AsyncArticleRepo
from cti_core.db.repositories.story import AsyncStoryRepo, StoryMember, StoryRepo
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

NOW = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.UTC)


def _article(session: Session, n: int, source: str, story_id: int | None = None) -> int:
    article = ArticleRepo(session).upsert(
        url=f"https://example.com/story-{n}-{source}", title=f"T{n}", source=source
    )
    article.story_id = story_id
    session.flush()
    return article.id


def test_create_then_candidates(db_session: Session) -> None:
    repo = StoryRepo(db_session)
    story_id = repo.create(title="Big breach", source="A", cve_ids={"CVE-2026-1"}, now=NOW)

    found = repo.candidates(NOW + dt.timedelta(hours=1), window_hours=72, max_age_days=7)
    mine = [c for c in found if c.id == story_id]
    assert len(mine) == 1
    assert mine[0].members == [StoryMember(title="Big breach", source="A")]
    assert mine[0].has_classify is False
    assert mine[0].cve_ids == frozenset({"CVE-2026-1"})

    later = repo.candidates(NOW + dt.timedelta(hours=73), window_hours=72, max_age_days=7)
    assert story_id not in {c.id for c in later}

    old = Story(
        title="Old",
        lead_source="A",
        first_seen_at=NOW - dt.timedelta(days=8),
        last_seen_at=NOW - dt.timedelta(hours=1),
    )
    db_session.add(old)
    db_session.flush()
    again = repo.candidates(NOW, window_hours=72, max_age_days=7)
    assert old.id not in {c.id for c in again}


def test_candidates_members_from_attached_articles(db_session: Session) -> None:
    repo = StoryRepo(db_session)
    story_id = repo.create(title="Lead", source="A", cve_ids=set(), now=NOW)
    first = _article(db_session, 1, "A", story_id)
    _article(db_session, 2, "B", story_id)
    repo.attach(
        story_id, article_id=first, cve_ids=set(), now=NOW, classify={"related_cyber": True}
    )

    cand = next(
        c for c in repo.candidates(NOW, window_hours=72, max_age_days=7) if c.id == story_id
    )
    assert sorted((m.title, m.source) for m in cand.members) == [("T1", "A"), ("T2", "B")]
    assert cand.has_classify is True


def test_attach_updates_counts(db_session: Session) -> None:
    repo = StoryRepo(db_session)
    story_id = repo.create(title="Lead", source="A", cve_ids={"CVE-2026-1"}, now=NOW)
    a1 = _article(db_session, 1, "A", story_id)
    repo.attach(story_id, article_id=a1, cve_ids={"CVE-2026-1"}, now=NOW, classify=None)
    a2 = _article(db_session, 2, "A", story_id)
    repo.attach(
        story_id,
        article_id=a2,
        cve_ids={"CVE-2026-2"},
        now=NOW + dt.timedelta(hours=1),
        classify={"related_cyber": True, "n": 1},
    )
    a3 = _article(db_session, 3, "B", story_id)
    repo.attach(
        story_id,
        article_id=a3,
        cve_ids=set(),
        now=NOW + dt.timedelta(hours=2),
        classify={"related_cyber": True, "n": 2},
    )

    db_session.expire_all()
    story = db_session.get(Story, story_id)
    assert story is not None
    assert story.article_count == 3
    assert story.source_count == 2
    assert sorted(story.cve_ids) == ["CVE-2026-1", "CVE-2026-2"]
    assert story.lead_article_id == a1
    assert story.classify == {"related_cyber": True, "n": 1}
    assert story.last_seen_at == NOW + dt.timedelta(hours=2)
    assert repo.get_inherit(story_id) == ({"related_cyber": True, "n": 1}, a1)


def test_get_inherit_empty_story(db_session: Session) -> None:
    repo = StoryRepo(db_session)
    story_id = repo.create(title="Lead", source="A", cve_ids=set(), now=NOW)
    assert repo.get_inherit(story_id) == (None, None)


def test_discard_if_empty(db_session: Session) -> None:
    repo = StoryRepo(db_session)
    empty = repo.create(title="E", source="A", cve_ids=set(), now=NOW)
    full = repo.create(title="F", source="A", cve_ids=set(), now=NOW)
    repo.attach(
        full, article_id=_article(db_session, 1, "A", full), cve_ids=set(), now=NOW, classify=None
    )

    assert repo.discard_if_empty(empty) is True
    assert repo.discard_if_empty(full) is False
    assert db_session.get(Story, empty) is None
    assert db_session.get(Story, full) is not None


def test_purge_empty(db_session: Session) -> None:
    repo = StoryRepo(db_session)
    old_empty = repo.create(title="E1", source="A", cve_ids=set(), now=NOW)
    old_full = repo.create(title="F1", source="A", cve_ids=set(), now=NOW)
    repo.attach(
        old_full,
        article_id=_article(db_session, 1, "A", old_full),
        cve_ids=set(),
        now=NOW,
        classify=None,
    )
    db_session.execute(Story.__table__.update().values(created_at=NOW - dt.timedelta(days=2)))
    young_empty = repo.create(title="E2", source="A", cve_ids=set(), now=NOW)
    db_session.flush()

    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
    assert repo.purge_empty(cutoff) >= 1
    db_session.expire_all()
    assert db_session.get(Story, old_empty) is None
    assert db_session.get(Story, old_full) is not None
    assert db_session.get(Story, young_empty) is not None


def test_concurrent_resolve_creates_one_story(_migrated_schema: None) -> None:
    title = "Concurrent story title xyz"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            with sync_session() as session:
                repo = StoryRepo(session)
                barrier.wait(timeout=10)
                repo.lock()
                now = dt.datetime.now(dt.UTC)
                found = repo.candidates(now, window_hours=72, max_age_days=7)
                if not any(m.title == title for c in found for m in c.members):
                    repo.create(title=title, source="A", cve_ids=set(), now=now)
        except BaseException as exc:
            errors.append(exc)

    try:
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not errors
        with sync_session() as session:
            count = session.scalar(
                select(func.count()).select_from(Story).where(Story.title == title)
            )
        assert count == 1
    finally:
        with sync_session() as session:
            session.execute(delete(Story).where(Story.title == title))


@pytest.mark.asyncio
async def test_async_counts_and_stats(async_db_session: AsyncSession) -> None:
    articles = AsyncArticleRepo(async_db_session)
    story = Story(title="S", lead_source="A", article_count=3, source_count=2)
    async_db_session.add(story)
    await async_db_session.flush()
    since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    for n, (match, raw) in enumerate(
        [
            ("lead", {}),
            ("cve", {"classify": {"inherited_from_story": 1}}),
            ("title", {"classify": {"other": 1}}),
        ]
    ):
        a = await articles.upsert(url=f"https://example.com/async-{n}", title=f"A{n}", source="s")
        await async_db_session.execute(
            Article.__table__.update()
            .where(Article.id == a.id)
            .values(story_id=story.id, story_match=match, raw_enrichment=raw)
        )

    repo = AsyncStoryRepo(async_db_session)
    assert await repo.counts([story.id, 999_999_999]) == {story.id: (3, 2)}
    assert await repo.counts([]) == {}
    stats = await repo.stats_since(since)
    assert (stats.followups, stats.inherited) == (2, 1)
    assert stats.new_stories >= 1
