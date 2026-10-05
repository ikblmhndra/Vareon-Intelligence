"""Snapshot test `routers/filtered_articles.py` -- Fase 7.6 (lanjutan
pola pilot `test_cve_router_snapshot.py`)."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.models.article import RejectedArticle
from cti_core.db.repositories.article import AsyncRejectedArticleRepo
from cti_core.urlkit import url_hash
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_URL = "https://example.com/vendor-marketing-post"

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?rejected_at$": (str,),
    },
    regex=True,
    strict=False,
)


async def _seed_rejected(session: AsyncSession) -> None:
    session.add(
        RejectedArticle(
            url=_URL,
            url_hash=url_hash(_URL),
            title="New product launch: SuperWidget 3000",
            source="vendorblog",
            posted_on=datetime.date(2026, 9, 1),
            reason="Vendor marketing, not threat intelligence",
        )
    )
    await session.flush()


async def test_list_filtered(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_rejected(api_session)
    resp = await api_client.get("/api/filtered-articles", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_restore_article(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_rejected(api_session)
    rows, _ = await AsyncRejectedArticleRepo(api_session).list_filtered(page=1, page_size=10)
    resp = await api_client.post(
        f"/api/filtered-articles/{rows[0].id}/restore", headers=auth_header()
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot
