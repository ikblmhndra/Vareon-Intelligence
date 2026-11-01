"""`ArticleOut` membawa sumber TTP/industri + malware, dan filter `ttp_source` (P4)."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.repositories.article import AsyncArticleRepo, MentionInput
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> tuple[int, int]:
    await AsyncClientRepo(session).ensure_default()
    repo = AsyncArticleRepo(session)
    today = datetime.date.today()
    a = await repo.upsert(url="https://x.example/a", title="A", source="S", posted_on=today)
    b = await repo.upsert(url="https://x.example/b", title="B", source="S", posted_on=today)
    aid, bid = a.id, b.id
    await repo.add_mentions(
        a,
        [
            MentionInput(
                "attack-pattern",
                "Phishing",
                "explicit",
                "T1566",
                evidence="used phishing",
                external_id="T1566",
            ),
            MentionInput("attack-pattern", "Scripting", "llm", "T1059", external_id="T1059"),
            MentionInput("tool", "Mimikatz", "dictionary", "Mimikatz"),
            MentionInput("identity", "Finance", "keyword", "Finance"),
            MentionInput("intrusion-set", "Grp", "llm", "Grp"),
        ],
    )
    await repo.add_mentions(
        b,
        [
            MentionInput("attack-pattern", "Phishing", "llm", "T1566", external_id="T1566"),
            MentionInput("intrusion-set", "Grp", "llm", "Grp"),
        ],
    )
    await session.commit()
    session.expire_all()
    return aid, bid


async def test_article_out_has_sources_and_malware(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    aid, _bid = await _seed(api_session)
    resp = await api_client.get(f"/api/articles/{aid}", headers=auth_header())
    body = resp.json()
    by_id = {t["id"]: t for t in body["ttps"]}
    assert by_id["T1566"]["source"] == "explicit"
    assert by_id["T1566"]["evidence"] == "used phishing"
    assert by_id["T1059"]["source"] == "llm"
    assert by_id["T1059"]["evidence"] is None
    assert body["malware"] == [{"name": "Mimikatz", "kind": "tool"}]
    assert body["industry_source"] == "keyword"


async def test_ttp_source_filter_list_and_heatmap(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    aid, bid = await _seed(api_session)
    resp = await api_client.get("/api/articles?ttp_source=explicit", headers=auth_header())
    assert {x["id"] for x in resp.json()["articles"]} == {aid}

    # dua sumber digabung; T1566 saja + sumber llm -> hanya artikel b
    resp = await api_client.get("/api/articles?ttp_source=llm&ttp=T1566", headers=auth_header())
    assert {x["id"] for x in resp.json()["articles"]} == {bid}

    resp = await api_client.get("/api/articles?ttp_source=bogus", headers=auth_header())
    assert resp.status_code == 422

    heat = await api_client.get("/api/mitre/heatmap?ttp_source=explicit", headers=auth_header())
    assert [t["id"] for t in heat.json()["ttps"]] == ["T1566"]
    assert heat.json()["matrix"] == [[1]]  # hanya baris explicit (artikel a)

    heat = await api_client.get("/api/mitre/heatmap", headers=auth_header())
    assert heat.json()["max_val"] == 2  # tanpa filter: T1566 di kedua artikel
