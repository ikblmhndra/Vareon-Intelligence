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


async def _seed_failed(session: AsyncSession) -> int:
    url = "https://example.com/failed-enrichment"
    row = RejectedArticle(
        url=url,
        url_hash=url_hash(url),
        title="BeyondTrust zero-day exploited",
        source="darkreading",
        scraper_id="darkreading",
        posted_on=datetime.date(2026, 10, 16),
        reason="[enrichment_failed] BadRequestError: Unsupported model",
        failure_kind="permanent",
    )
    session.add(row)
    await session.flush()
    return row.id


async def test_kind_failed_is_gone_and_unrelated_still_filters(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_rejected(api_session)
    await _seed_failed(api_session)

    async def get(kind: str) -> object:
        return await api_client.get(
            "/api/filtered-articles", params={"kind": kind}, headers=auth_header()
        )

    assert (await get("failed")).status_code == 422  # type: ignore[attr-defined]
    unrelated = await get("unrelated")
    assert [i["title"] for i in unrelated.json()["items"]] == [  # type: ignore[attr-defined]
        "New product launch: SuperWidget 3000"
    ]


async def test_replay_endpoint_is_gone(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    rejected_id = await _seed_failed(api_session)
    resp = await api_client.post(
        f"/api/filtered-articles/{rejected_id}/replay", headers=auth_header()
    )
    assert resp.status_code in (404, 405)


async def test_restore_refuses_a_failed_enrichment_row(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """Baris gagal-enrich peninggalan sebelum P7g tidak boleh di-restore (tanpa enrichment)."""
    rejected_id = await _seed_failed(api_session)

    resp = await api_client.post(
        f"/api/filtered-articles/{rejected_id}/restore", headers=auth_header()
    )

    assert resp.status_code == 409 and "legacy" in resp.json()["detail"]


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


async def test_restore_article_is_assessed(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """Artikel hasil restore langsung punya penilaian Admiralty: tanpa itu chip-nya kosong dan
    tiap start API melihat `credibility IS NULL` lalu enqueue recompute_all penuh."""
    from cti_core.db.models.article import Article
    from sqlalchemy import select

    await _seed_rejected(api_session)
    rows, _ = await AsyncRejectedArticleRepo(api_session).list_filtered(page=1, page_size=10)
    resp = await api_client.post(
        f"/api/filtered-articles/{rows[0].id}/restore", headers=auth_header()
    )
    assert resp.status_code == 200

    credibility = (
        await api_session.execute(select(Article.credibility).where(Article.url == _URL))
    ).scalar_one()
    assert credibility is not None
