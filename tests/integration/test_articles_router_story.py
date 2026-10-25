"""`GET /api/articles` membawa referensi story + filter `story_id` (P3, story dedup)."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.models.story import Story
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _seed(api_session: AsyncSession) -> tuple[int, int, int, int]:
    """Satu story (lead + follow-up warisan), satu artikel tanpa story."""
    await AsyncClientRepo(api_session).ensure_default()
    now = datetime.datetime.now(datetime.UTC)
    today = now.date()
    story = Story(
        title="Big breach",
        lead_source="A",
        first_seen_at=now,
        last_seen_at=now,
        article_count=2,
        source_count=2,
    )
    api_session.add(story)
    await api_session.flush()
    repo = AsyncArticleRepo(api_session)
    lead = await repo.upsert(
        url="https://s.example/lead", title="Big breach", source="A", posted_on=today
    )
    follow = await repo.upsert(
        url="https://s.example/follow", title="Big breach again", source="B", posted_on=today
    )
    plain = await repo.upsert(
        url="https://s.example/plain", title="Unrelated", source="C", posted_on=today
    )
    lead.story_id = story.id
    follow.story_id = story.id
    follow.story_match = "cve"
    follow.raw_enrichment = {
        "classify": {
            "inherited_from_story": story.id,
            "lead_article_id": lead.id,
            "match": "cve",
        }
    }
    await api_session.commit()
    return story.id, lead.id, follow.id, plain.id


async def test_story_id_filter_lists_members_with_story_ref(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    story_id, lead_id, follow_id, _plain_id = await _seed(api_session)

    resp = await api_client.get(f"/api/articles?story_id={story_id}", headers=auth_header())
    assert resp.status_code == 200
    body = resp.json()
    by_id = {a["id"]: a for a in body["articles"]}
    assert set(by_id) == {lead_id, follow_id}
    assert body["total"] == 2
    ref = {"id": story_id, "article_count": 2, "source_count": 2}
    assert by_id[lead_id]["story"] == ref
    assert by_id[follow_id]["story"] == ref
    assert by_id[lead_id]["classify_inherited_from"] is None
    assert by_id[follow_id]["classify_inherited_from"] == lead_id

    # dedup=true memakai jalur serialisasi lain: story tetap terisi
    resp = await api_client.get(
        f"/api/articles?story_id={story_id}&dedup=true", headers=auth_header()
    )
    assert all(a["story"] == ref for a in resp.json()["articles"])


async def test_article_without_story_and_detail(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    story_id, lead_id, follow_id, plain_id = await _seed(api_session)

    resp = await api_client.get("/api/articles", headers=auth_header())
    by_id = {a["id"]: a for a in resp.json()["articles"]}
    assert by_id[plain_id]["story"] is None
    assert by_id[plain_id]["classify_inherited_from"] is None

    detail = (await api_client.get(f"/api/articles/{follow_id}", headers=auth_header())).json()
    assert detail["story"] == {"id": story_id, "article_count": 2, "source_count": 2}
    assert detail["classify_inherited_from"] == lead_id
    plain = (await api_client.get(f"/api/articles/{plain_id}", headers=auth_header())).json()
    assert plain["story"] is None
