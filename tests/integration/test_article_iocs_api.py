"""`GET /api/articles/{id}/iocs` (5c B-N5): IOC sebuah artikel dengan konteks sumber artikel
itu dan label reputasi dari kartu provider yang tersimpan."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _article(session: AsyncSession, slug: str = "a") -> int:
    await AsyncClientRepo(session).ensure_default()
    article = await AsyncArticleRepo(session).upsert(
        url=f"https://s.example/{slug}",
        title=slug,
        source="S",
        posted_on=datetime.date.today(),
    )
    await session.commit()
    return article.id


async def _ioc(
    session: AsyncSession,
    article_id: int,
    type_: str,
    value: str,
    context: str | None = None,
    *,
    suppression_reason: str | None = None,
    source: str = "s1",
) -> None:
    await AsyncIndicatorRepo(session).upsert(
        type=type_,
        value=value,
        source_url=f"https://{source}.example/x",
        source_name=source,
        context=context,
        article_id=article_id,
        suppression_reason=suppression_reason,
    )


async def test_article_iocs_two_sources_first_context(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    aid = await _article(api_session)
    # indikator yang sama terlihat dua kali di artikel ini: konteks kosong dulu, lalu berisi.
    await _ioc(api_session, aid, "domain", "evil.example", None, source="s1")
    await _ioc(api_session, aid, "domain", "evil.example", "C2 server", source="s2")
    await _ioc(api_session, aid, "ip", "203.0.113.9", "dropper host")
    await api_session.commit()

    resp = await api_client.get(f"/api/articles/{aid}/iocs", headers=auth_header())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert [(i["type"], i["value"], i["context"]) for i in body["items"]] == [
        ("domain", "evil.example", "C2 server"),
        ("ip", "203.0.113.9", "dropper host"),
    ]
    assert all(i["reputation"] is None for i in body["items"])


async def test_article_iocs_excludes_unusable(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    aid = await _article(api_session)
    await _ioc(api_session, aid, "domain", "ok.example")
    await _ioc(api_session, aid, "domain", "allowlisted.example", suppression_reason="allowlist")
    await api_session.commit()

    body = (await api_client.get(f"/api/articles/{aid}/iocs", headers=auth_header())).json()
    assert body["total"] == 1
    assert [i["value"] for i in body["items"]] == ["ok.example"]


async def test_article_iocs_reputation_from_card(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    aid = await _article(api_session)
    await _ioc(api_session, aid, "ip", "198.51.100.7")
    indicator = (await AsyncIndicatorRepo(api_session).list_by_article_ids([aid]))[0]
    now = datetime.datetime.now(datetime.UTC)
    repo = AsyncIndicatorRepo(api_session)
    await repo.set_enrichment_provider(
        indicator,
        {"key": "abuseipdb", "name": "AbuseIPDB", "verdict": "clean", "score": 0},
        now=now,
    )
    await repo.set_enrichment_provider(
        indicator,
        {"key": "virustotal", "name": "VirusTotal", "verdict": "malicious", "score": 90},
        now=now,
    )
    await api_session.commit()

    body = (await api_client.get(f"/api/articles/{aid}/iocs", headers=auth_header())).json()
    assert body["items"][0]["reputation"] == "malicious (VirusTotal)"


async def test_article_iocs_total_and_cap(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    aid = await _article(api_session)
    for n in range(205):
        await _ioc(api_session, aid, "domain", f"h{n:03d}.example")
    await api_session.commit()

    body = (await api_client.get(f"/api/articles/{aid}/iocs", headers=auth_header())).json()
    assert body["total"] == 205
    assert len(body["items"]) == 200
    assert body["items"][0]["value"] == "h000.example"


async def test_article_iocs_unknown_article_404(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    resp = await api_client.get("/api/articles/999999/iocs", headers=auth_header())
    assert resp.status_code == 404


async def test_article_iocs_requires_auth(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/articles/1/iocs")
    assert resp.status_code == 401


async def test_article_iocs_requires_view_news(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    resp = await api_client.get(
        "/api/articles/1/iocs", headers=auth_header(username="bob", role="nobody")
    )
    assert resp.status_code == 403
