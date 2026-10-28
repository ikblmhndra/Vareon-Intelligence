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


async def test_kind_filter_separates_failed_from_unrelated(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_rejected(api_session)
    await _seed_failed(api_session)

    async def titles(kind: str) -> list[str]:
        resp = await api_client.get(
            "/api/filtered-articles", params={"kind": kind}, headers=auth_header()
        )
        assert resp.status_code == 200
        return [i["title"] for i in resp.json()["items"]]

    assert await titles("failed") == ["BeyondTrust zero-day exploited"]
    assert await titles("unrelated") == ["New product launch: SuperWidget 3000"]
    assert len(await titles("all")) == 2


async def test_replay_sends_a_silent_enrich_task_and_writes_the_audit_log(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cti_core.db.models.auth import AuditLogEntry
    from sqlalchemy import select

    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        "cti_api.routers.filtered_articles.send_enrich_task", lambda **kw: sent.append(kw)
    )
    rejected_id = await _seed_failed(api_session)

    resp = await api_client.post(
        f"/api/filtered-articles/{rejected_id}/replay", headers=auth_header()
    )

    assert resp.status_code == 200 and resp.json() == {"success": True}
    [call] = sent
    assert call["url"] == "https://example.com/failed-enrichment" and call["replay"] is True
    assert call["posted_on"] == datetime.date(2026, 10, 16) and call["scraper_id"] == "darkreading"
    entry = (
        await api_session.execute(
            select(AuditLogEntry).where(AuditLogEntry.action == "replay_enrichment")
        )
    ).scalar_one()
    assert entry.target_id == str(rejected_id) and entry.detail["failure_kind"] == "permanent"


async def test_replay_is_admin_only_and_refuses_what_it_cannot_replay(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cti_api.routers.filtered_articles.send_enrich_task", lambda **_kw: None)
    failed_id = await _seed_failed(api_session)
    await _seed_rejected(api_session)
    rows, _ = await AsyncRejectedArticleRepo(api_session).list_filtered(kind="unrelated")
    url = f"/api/filtered-articles/{failed_id}/replay"

    analyst = await api_client.post(url, headers=auth_header(role="analyst"))
    missing = await api_client.post("/api/filtered-articles/999999/replay", headers=auth_header())
    not_failed = await api_client.post(
        f"/api/filtered-articles/{rows[0].id}/replay", headers=auth_header()
    )

    assert (analyst.status_code, missing.status_code, not_failed.status_code) == (403, 404, 409)


async def test_replay_refuses_a_url_that_is_already_an_article(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cti_core.db.repositories.article import AsyncArticleRepo

    monkeypatch.setattr("cti_api.routers.filtered_articles.send_enrich_task", lambda **_kw: None)
    rejected_id = await _seed_failed(api_session)
    await AsyncArticleRepo(api_session).upsert(
        url="https://example.com/failed-enrichment",
        title="Stub",
        source="darkreading",
        news_type="Manually Restored",
    )

    resp = await api_client.post(
        f"/api/filtered-articles/{rejected_id}/replay", headers=auth_header()
    )

    assert resp.status_code == 409 and "already an article" in resp.json()["detail"]


async def test_restore_refuses_a_failed_enrichment_row(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """Restore tidak meng-enrich dan stub-nya memblokir replay: baris gagal harus lewat Replay."""
    rejected_id = await _seed_failed(api_session)

    resp = await api_client.post(
        f"/api/filtered-articles/{rejected_id}/restore", headers=auth_header()
    )

    assert resp.status_code == 409 and "Replay" in resp.json()["detail"]


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
