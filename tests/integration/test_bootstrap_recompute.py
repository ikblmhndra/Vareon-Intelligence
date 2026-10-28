"""Lifespan API: artikel tanpa `credibility` memicu satu recompute-all walau tidak ada grade
bawaan baru (P6 4.4)."""

from __future__ import annotations

import pytest
from cti_core.db.engine import async_session
from cti_core.db.models.article import Article
from cti_core.db.repositories.article import AsyncArticleRepo
from sqlalchemy import delete

from tests.integration.test_lifespan_recompute import (
    _keep_logging_config as _keep_logging_config,
)
from tests.integration.test_lifespan_recompute import (
    _no_default_rows as _no_default_rows,
)
from tests.integration.test_lifespan_recompute import (
    _run_lifespan,
)

pytestmark = pytest.mark.asyncio


async def test_startup_enqueues_once_for_unassessed_articles(
    _no_default_rows: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr("cti_api.main.send_recompute_all", lambda: calls.append(1))
    await _run_lifespan()  # membuat grade bawaan; antrean pertama
    calls.clear()

    async with async_session() as s:
        await s.execute(delete(Article))
        await AsyncArticleRepo(s).upsert(url="https://example.com/boot", title="B", source="S")
        await s.commit()
    try:
        await _run_lifespan()  # tidak ada baris baru, tapi ada artikel credibility NULL
        assert calls == [1]
    finally:
        async with async_session() as s:
            await s.execute(delete(Article).where(Article.url == "https://example.com/boot"))
            await s.commit()
