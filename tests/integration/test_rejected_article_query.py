"""Integration test `RejectedArticleRepo` (sync, jalur tulis)/
`AsyncRejectedArticleRepo` (async, baca+restore) + wiring
`cti_enrich.stages.persist.persist_rejected()` -- Postgres REAL
(testcontainers). Fase 7.3 (router `filtered_articles`)."""

from __future__ import annotations

import datetime

from cti_core.db.repositories.article import (
    AsyncArticleRepo,
    AsyncRejectedArticleRepo,
    RejectedArticleRepo,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


class TestRejectedArticleRepoSync:
    def test_upsert_creates_then_dedups_by_url(self, db_session: Session) -> None:
        repo = RejectedArticleRepo(db_session)
        first = repo.upsert(
            url="https://example.com/not-cyber",
            title="Best pasta recipes for a Tuesday night",
            source="test-feed",
            scraper_id="test_scraper",
            reason="Article gak berkaitan sama keamanan siber",
        )
        assert first.reason == "Article gak berkaitan sama keamanan siber"

        second = repo.upsert(
            url="https://example.com/not-cyber",
            title="Best pasta recipes for a Tuesday night (updated)",
            source="test-feed",
            reason="reason baru",
        )
        assert second.id == first.id
        assert second.title.endswith("(updated)")
        assert second.reason == "reason baru"

    def test_failure_kind_is_overwritten_even_by_none(self, db_session: Session) -> None:
        """Replay yang kemudian DITOLAK klasifikasi tidak boleh tetap bertanda gagal."""
        repo = RejectedArticleRepo(db_session)
        failed = repo.upsert(
            url="https://example.com/replay",
            title="T",
            source="test",
            reason="[enrichment_failed] X: boom",
            failure_kind="permanent",
        )
        assert failed.failure_kind == "permanent"

        rejected = repo.upsert(
            url="https://example.com/replay", title="T", source="test", reason="not cyber"
        )
        assert rejected.id == failed.id and rejected.failure_kind is None

    def test_upsert_sets_url_hash(self, db_session: Session) -> None:
        from cti_core.urlkit import url_hash as compute_url_hash

        repo = RejectedArticleRepo(db_session)
        row = repo.upsert(url="https://example.com/x", title="X", source="test")
        assert row.url_hash == compute_url_hash("https://example.com/x")


async def _seed_rejected(session: AsyncSession, *, count: int = 1) -> list[int]:
    from cti_core.db.models.article import RejectedArticle

    ids = []
    for i in range(count):
        row = RejectedArticle(
            url=f"https://example.com/reject-{i}",
            url_hash=f"hash-reject-{i}",
            title=f"Unrelated article {i}",
            source="test-feed",
            reason="not cyber related",
        )
        session.add(row)
        await session.flush()
        ids.append(row.id)
    return ids


class TestAsyncRejectedArticleRepo:
    async def test_list_filtered_returns_newest_first(self, async_db_session: AsyncSession) -> None:
        from cti_core.db.models.article import RejectedArticle

        async_db_session.add(
            RejectedArticle(
                url="https://example.com/a",
                url_hash="hash-a",
                title="Article A",
                source="feed",
                rejected_at=datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC),
            )
        )
        async_db_session.add(
            RejectedArticle(
                url="https://example.com/b",
                url_hash="hash-b",
                title="Article B",
                source="feed",
                rejected_at=datetime.datetime(2026, 9, 5, tzinfo=datetime.UTC),
            )
        )
        await async_db_session.flush()

        repo = AsyncRejectedArticleRepo(async_db_session)
        rows, total = await repo.list_filtered()
        assert total == 2
        assert rows[0].title == "Article B"

    async def test_list_filtered_by_search_matches_title_or_source(
        self, async_db_session: AsyncSession
    ) -> None:
        from cti_core.db.models.article import RejectedArticle

        async_db_session.add(
            RejectedArticle(
                url="https://example.com/pasta",
                url_hash="hash-pasta",
                title="Best pasta recipes",
                source="foodblog",
            )
        )
        async_db_session.add(
            RejectedArticle(
                url="https://example.com/other",
                url_hash="hash-other",
                title="Something else",
                source="othersource",
            )
        )
        await async_db_session.flush()

        repo = AsyncRejectedArticleRepo(async_db_session)
        rows, total = await repo.list_filtered(search="pasta")
        assert total == 1
        assert rows[0].title == "Best pasta recipes"

    async def test_get_by_id_returns_none_for_missing(self, async_db_session: AsyncSession) -> None:
        repo = AsyncRejectedArticleRepo(async_db_session)
        assert await repo.get_by_id(999999) is None

    async def test_restore_inserts_new_article(self, async_db_session: AsyncSession) -> None:
        ids = await _seed_rejected(async_db_session)
        repo = AsyncRejectedArticleRepo(async_db_session)
        rejected = await repo.get_by_id(ids[0])
        assert rejected is not None

        article_repo = AsyncArticleRepo(async_db_session)
        article = await repo.restore(rejected, article_repo)
        assert article.news_type == "Manually Restored"
        assert article.url == rejected.url

    async def test_restore_is_noop_when_article_already_exists(
        self, async_db_session: AsyncSession
    ) -> None:
        """Port perilaku lama: kalau artikel udah ADA (misal keterima
        normal lewat enrichment), restore() gak boleh NIMPA -- cuma
        balikin yang udah ada apa adanya."""
        article_repo = AsyncArticleRepo(async_db_session)
        real_article = await article_repo.upsert(
            url="https://example.com/already-real",
            title="Real accepted article",
            source="realfeed",
            news_type="global",
            confidence_score=90,
        )

        from cti_core.db.models.article import RejectedArticle

        rejected = RejectedArticle(
            url="https://example.com/already-real",
            url_hash="irrelevant-hash-since-not-queried-by-this",
            title="Rejected duplicate view of the same URL",
            source="realfeed",
        )
        async_db_session.add(rejected)
        await async_db_session.flush()

        repo = AsyncRejectedArticleRepo(async_db_session)
        result = await repo.restore(rejected, article_repo)
        assert result.id == real_article.id
        assert result.news_type == "global"  # TIDAK ketimpa "Manually Restored"
