"""Task `confidence.refresh_stories` (P6 4.2) -- Postgres REAL, Redis diganti stub dict."""

from __future__ import annotations

import datetime

import pytest
import redis
from cti_core.db.models.article import Article
from cti_core.db.models.article_cve import ArticleCve
from cti_core.db.models.story import Story
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.source_reliability import AsyncSourceReliabilityRepo
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value.encode()


class DownRedis:
    def get(self, key: str) -> bytes | None:
        raise redis.ConnectionError("down")

    def set(self, key: str, value: str) -> None:
        raise redis.ConnectionError("down")


def _task():
    from cti_worker.tasks import confidence

    return confidence


async def _credibility(s: AsyncSession, article_id: int) -> int | None:
    return (
        await s.execute(select(Article.credibility).where(Article.id == article_id))
    ).scalar_one()


async def _story(s: AsyncSession) -> Story:
    now = datetime.datetime.now(datetime.UTC)
    story = Story(title="t", lead_source="a", first_seen_at=now, last_seen_at=now)
    s.add(story)
    await s.flush()
    return story


async def test_refresh_raises_older_member_to_1(async_db_session: AsyncSession) -> None:
    s = async_db_session
    story = await _story(s)
    story.source_count = 2  # yang dijaga `StoryRepo.attach` saat anggota menempel
    for name in ("SrcA", "SrcB", "SrcC"):
        await AsyncSourceReliabilityRepo(s).add_entry(
            source_name=name,
            analyst_name="analyst1",
            reliability_grade="B",
            credibility_code="2",
            notes="",
        )
    repo = AsyncArticleRepo(s)
    target = await repo.upsert(
        url="https://example.com/r1", title="T", source="SrcA", story_id=story.id
    )
    await s.flush()
    s.add(ArticleCve(article_id=target.id, cve_id="CVE-2026-0001"))
    await repo.upsert(url="https://example.com/r2", title="T", source="SrcB", story_id=story.id)
    target_id, story_id = target.id, story.id
    await s.commit()
    redis_client = FakeRedis()
    now = datetime.datetime.now(datetime.UTC)

    # dua sumber + CVE -> 2 (tegaskan titik awal, lalu tambah sumber ketiga)
    await _task().refresh_stories(s, redis_client, now)
    assert await _credibility(s, target_id) == 2
    await repo.upsert(url="https://example.com/r3", title="T", source="SrcC", story_id=story_id)
    await s.execute(
        update(Story).where(Story.id == story_id).values(updated_at=now, source_count=3)
    )
    await s.commit()

    result = await _task().refresh_stories(s, redis_client, now + datetime.timedelta(seconds=1))

    assert result["stories"] >= 1
    assert await _credibility(s, target_id) == 1
    assert (
        redis_client.data[_task().WATERMARK_KEY]
        .decode()
        .startswith((now + datetime.timedelta(seconds=1)).isoformat()[:19])
    )


async def test_refresh_without_watermark_looks_back_24h(async_db_session: AsyncSession) -> None:
    s = async_db_session
    now = datetime.datetime.now(datetime.UTC)
    old, recent = await _story(s), await _story(s)
    repo = AsyncArticleRepo(s)
    a_old = await repo.upsert(url="https://example.com/o", title="O", source="S", story_id=old.id)
    a_new = await repo.upsert(
        url="https://example.com/n", title="N", source="S", story_id=recent.id
    )
    old_aid, new_aid = a_old.id, a_new.id
    await s.execute(
        update(Story)
        .where(Story.id == old.id)
        .values(updated_at=now - datetime.timedelta(hours=30))
    )
    await s.execute(
        update(Story)
        .where(Story.id == recent.id)
        .values(updated_at=now - datetime.timedelta(hours=1))
    )
    await s.commit()

    await _task().refresh_stories(s, FakeRedis(), now)

    assert await _credibility(s, old_aid) is None
    assert await _credibility(s, new_aid) is not None


async def test_refresh_redis_down_raises_without_updates(async_db_session: AsyncSession) -> None:
    s = async_db_session
    story = await _story(s)
    art = await AsyncArticleRepo(s).upsert(
        url="https://example.com/d", title="D", source="S", story_id=story.id
    )
    art_id = art.id
    await s.commit()

    with pytest.raises(redis.ConnectionError):
        await _task().refresh_stories(s, DownRedis(), datetime.datetime.now(datetime.UTC))

    assert await _credibility(s, art_id) is None


async def test_refresh_overlaps_watermark_for_late_commits(async_db_session: AsyncSession) -> None:
    """`updated_at = now()` = waktu MULAI transaksi enrich; commit yang telat (sesudah query
    run sebelumnya) punya `updated_at` < watermark tapi tetap harus terambil."""
    s = async_db_session
    now = datetime.datetime.now(datetime.UTC)
    watermark = now - datetime.timedelta(minutes=10)
    story = await _story(s)
    art = await AsyncArticleRepo(s).upsert(
        url="https://example.com/late", title="L", source="S", story_id=story.id
    )
    art_id = art.id
    await s.execute(
        update(Story)
        .where(Story.id == story.id)
        .values(updated_at=watermark - datetime.timedelta(minutes=2))
    )
    await s.commit()
    redis_client = FakeRedis()
    redis_client.set(_task().WATERMARK_KEY, watermark.isoformat())

    await _task().refresh_stories(s, redis_client, now)

    assert await _credibility(s, art_id) is not None
