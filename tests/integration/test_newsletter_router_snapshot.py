"""Snapshot test `routers/newsletter.py` -- Fase 7.6 (lanjutan pola
pilot `test_cve_router_snapshot.py`).

`_enrich_articles()` (Playwright browser real + LLM summarization) di-
mock, titik yang SAMA persis kayak `test_newsletter_clusters.py` yang
udah ada. `create_graph_draft` (imported LANGSUNG ke namespace
`cti_api.routers.newsletter`, bukan cuma `cti_alerts.mailer`) di-patch
di titik importnya sendiri, bukan sumbernya -- match `from X import Y`
binding, bukan `import X`."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cti_api.services import newsletter as newsletter_service
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

# Dipin ke ISO week 39, 2026 (Senin 2026-09-21 s.d. Minggu 2026-09-27) supaya
# `week`/`year`/subject line di snapshot gak ikut geser tiap minggu kalender
# ASLI berganti -- lihat `newsletter_service._now()`.
_NOW = datetime.datetime(2026, 9, 24, 12, 0, tzinfo=datetime.UTC)

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?newsletter_id$": (int,),
        r"(.*\.)?created_at$": (str,),
        r"(.*\.)?generated_at$": (str,),
    },
    regex=True,
    strict=False,
)


async def _seed_article(session: AsyncSession) -> int:
    await AsyncClientRepo(session).ensure_default()
    a = await AsyncArticleRepo(session).upsert(
        url="https://example.com/highlight",
        title="APT41 breaches government network",
        source="gbhacker",
        posted_on=datetime.date(2026, 9, 1),
    )
    return a.id


def _fake_enrich_articles() -> AsyncMock:
    return AsyncMock(
        return_value=[
            {
                "id": 1,
                "title": "APT41 breaches government network",
                "url": "https://example.com/highlight",
                "source": "gbhacker",
                "key_points": ["Government network breached"],
                "summary": "APT41 breached a government network.",
            }
        ]
    )


async def test_source_hints(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/newsletter/source-hints", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_newsletter_history_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/newsletter/history", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_preview_newsletter(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    article_id = await _seed_article(api_session)
    with (
        patch.object(newsletter_service, "_enrich_articles", _fake_enrich_articles()),
        patch.object(newsletter_service, "_now", return_value=_NOW),
    ):
        resp = await api_client.post(
            "/api/newsletter/preview", headers=auth_header(), json={"highlight": article_id}
        )
    assert resp.status_code == 200
    body = resp.json()
    body.pop("html")  # HTML render -- bukan fokus shape test ini
    assert body == snapshot(matcher=_NORMALIZE)


async def test_get_saved_html(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    article_id = await _seed_article(api_session)
    with patch.object(newsletter_service, "_enrich_articles", _fake_enrich_articles()):
        preview_resp = await api_client.post(
            "/api/newsletter/preview", headers=auth_header(), json={"highlight": article_id}
        )
    newsletter_id = preview_resp.json()["newsletter_id"]
    resp = await api_client.get(f"/api/newsletter/{newsletter_id}/html", headers=auth_header())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert len(resp.text) > 0


async def test_resend_newsletter(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    article_id = await _seed_article(api_session)
    with (
        patch.object(newsletter_service, "_enrich_articles", _fake_enrich_articles()),
        patch.object(newsletter_service, "_now", return_value=_NOW),
    ):
        preview_resp = await api_client.post(
            "/api/newsletter/preview", headers=auth_header(), json={"highlight": article_id}
        )
    newsletter_id = preview_resp.json()["newsletter_id"]
    with patch(
        "cti_api.routers.newsletter.create_graph_draft", MagicMock(return_value="graph-msg-1")
    ):
        resp = await api_client.post(
            f"/api/newsletter/{newsletter_id}/resend", headers=auth_header()
        )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_draft_email(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    article_id = await _seed_article(api_session)
    with (
        patch.object(newsletter_service, "_enrich_articles", _fake_enrich_articles()),
        patch.object(newsletter_service, "_now", return_value=_NOW),
        patch(
            "cti_api.routers.newsletter.create_graph_draft", MagicMock(return_value="graph-msg-2")
        ),
    ):
        resp = await api_client.post(
            "/api/newsletter/draft-email", headers=auth_header(), json={"highlight": article_id}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body == snapshot(matcher=_NORMALIZE)
