"""Task `story.purge_empty` di Postgres beneran (testcontainers).

Task membuka `sync_session()` sendiri dan commit, jadi baris seed dibersihkan manual."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from cti_core.db.engine import sync_session
from cti_core.db.models.article import Article
from cti_core.db.models.story import Story
from cti_core.db.repositories.article import ArticleRepo
from cti_core.db.repositories.story import StoryRepo
from sqlalchemy import delete, select, update

NOW = dt.datetime.now(dt.UTC)


def _wipe() -> None:
    with sync_session() as s:
        s.execute(update(Article).values(story_id=None))
        s.execute(delete(Story))
        s.execute(delete(Article).where(Article.url.like("https://example.com/story-task-%")))


@pytest.fixture(autouse=True)
def _clean(_migrated_schema: None) -> Iterator[None]:
    _wipe()
    yield
    _wipe()


@pytest.fixture
def mod(_migrated_schema: None):
    # Import LAZY: `cti_worker.celery_app` baca settings + DB pas di-import.
    from cti_worker.tasks import story

    return story


def test_purge_empty_deletes_only_old_empty_stories(mod) -> None:
    with sync_session() as s:
        repo = StoryRepo(s)
        old_empty = repo.create(title="E1", source="A", cve_ids=set(), now=NOW)
        old_full = repo.create(title="F1", source="A", cve_ids=set(), now=NOW)
        article = ArticleRepo(s).upsert(
            url="https://example.com/story-task-1", title="T1", source="A"
        )
        article.story_id = old_full
        s.flush()
        repo.attach(old_full, article_id=article.id, cve_ids=set(), now=NOW, classify=None)
        s.execute(
            update(Story)
            .where(Story.id.in_([old_empty, old_full]))
            .values(created_at=NOW - dt.timedelta(days=8))
        )
        young_empty = repo.create(title="E2", source="A", cve_ids=set(), now=NOW)

    assert mod.purge_empty() == {"purged": 1}

    with sync_session() as s:
        ids = set(s.execute(select(Story.id)).scalars())
    assert ids == {old_full, young_empty}
