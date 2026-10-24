"""`/api/newsroom/topics` dan param `ttp`/`sort`/`confirmed_only` di `/api/articles`
lewat HTTP -- Postgres REAL."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_TODAY = datetime.date.today()


async def _seed(session: AsyncSession, title: str, day: datetime.date, **enrich: object) -> int:
    repo = AsyncArticleRepo(session)
    a = await repo.upsert(
        url=f"https://example.com/{title.replace(' ', '-')}", title=title, source="S", posted_on=day
    )
    await repo.set_enrichment(a, **enrich)  # type: ignore[arg-type]
    return a.id


async def test_topics_returns_latest_article_and_countries(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Test ini menguji label/penanda tren dengan baseline yang dianggap layak; aturan baseline
    # kosong (audit UI U4) diuji di `test_trending_without_a_usable_baseline_claims_no_rise`.
    from cti_api.services import trending as _trending

    monkeypatch.setattr(_trending, "PREV_MIN_DAY_COVERAGE", 0)
    _trending._CACHE.clear()
    await AsyncClientRepo(api_session).ensure_default()
    await _seed(
        api_session,
        "Qilin hits bank one",
        _TODAY - datetime.timedelta(days=2),
        threat_actors=["Qilin"],
        countries=[("SG", "victim")],
    )
    await _seed(
        api_session,
        "Qilin hits bank two",
        _TODAY - datetime.timedelta(days=1),
        threat_actors=["Qilin"],
        countries=[("ID", "victim")],
    )
    await _seed(
        api_session, "Qilin newest", _TODAY, threat_actors=["Qilin"], countries=[("SG", "victim")]
    )
    r = await api_client.get(
        "/api/newsroom/topics",
        params={"posted_on_start": (_TODAY - datetime.timedelta(days=6)).isoformat()},
        headers=auth_header(),
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["name"] == "Qilin"
    assert item["is_new"] is True
    assert set(item["top_countries"]) <= {"SG", "ID"}
    assert item["latest_article"]["title"] == "Qilin newest"


async def test_topics_respects_search(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    for i in range(3):
        await _seed(api_session, f"bank breach {i}", _TODAY, threat_actors=["Akira"])
    for i in range(3):
        await _seed(api_session, f"hospital leak {i}", _TODAY, threat_actors=["Medusa"])
    r = await api_client.get(
        "/api/newsroom/topics", params={"search": "bank"}, headers=auth_header()
    )
    assert r.status_code == 200, r.text
    assert [i["name"] for i in r.json()["items"]] == ["Akira"]
    assert r.json()["items"][0]["count"] == 3


async def test_articles_ttp_filter(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    await _seed(api_session, "uses powershell", _TODAY, ttps=[("T1059", "Command Interpreter")])
    await _seed(api_session, "uses phishing", _TODAY, ttps=[("T1566", "Phishing")])
    r = await api_client.get("/api/articles", params={"ttp": "T1059"}, headers=auth_header())
    assert r.status_code == 200, r.text
    assert [a["title"] for a in r.json()["articles"]] == ["uses powershell"]


async def test_articles_confirmed_only_and_priority(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    repo = AsyncArticleRepo(api_session)
    await repo.upsert(url="https://e.com/x", title="plain", source="S", posted_on=_TODAY)
    await repo.upsert(
        url="https://e.com/y",
        title="incident",
        source="S",
        posted_on=_TODAY - datetime.timedelta(days=3),
        confirmed_incident=True,
    )
    h = auth_header()
    r = await api_client.get("/api/articles", params={"confirmed_only": "true"}, headers=h)
    assert [a["title"] for a in r.json()["articles"]] == ["incident"]
    r = await api_client.get("/api/articles", params={"sort": "priority"}, headers=h)
    assert [a["title"] for a in r.json()["articles"]] == ["incident", "plain"]


async def test_topics_window_is_clamped(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    h = auth_header()
    r = await api_client.get(
        "/api/newsroom/topics", params={"posted_on_start": "0001-01-01"}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["window_days"] == 3650
    future = (_TODAY + datetime.timedelta(days=30)).isoformat()
    r = await api_client.get("/api/newsroom/topics", params={"posted_on_start": future}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["window_days"] == 1
