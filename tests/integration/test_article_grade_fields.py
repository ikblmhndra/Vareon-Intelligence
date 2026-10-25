"""`GET /api/articles` membawa kode Admiralty + asal grade source (Task 9, P2 cheap wins)."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.models import SourceReliabilityEntry
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_list_articles_carries_source_grade(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    today = datetime.date.today()
    api_session.add(
        SourceReliabilityEntry(
            source_name="GradedSource",
            analyst_name="system",
            reliability_grade="C",
            credibility_code="3",
            admiralty_code="C3",
            notes="",
            added_date=today,
            last_updated=today,
            origin="default",
        )
    )
    repo = AsyncArticleRepo(api_session)
    # nama source beda huruf besar/kecil dari baris rating: harus tetap cocok
    await repo.upsert(
        url="https://g.example/1", title="Graded one", source="gradedsource", posted_on=today
    )
    await repo.upsert(
        url="https://u.example/1", title="Ungraded one", source="NoSuchSource", posted_on=today
    )
    await api_session.commit()

    resp = await api_client.get("/api/articles", headers=auth_header())
    assert resp.status_code == 200
    by_source = {a["source"]: a for a in resp.json()["articles"]}
    assert by_source["gradedsource"]["admiralty_code"] == "C3"
    assert by_source["gradedsource"]["grade_origin"] == "default"
    assert by_source["NoSuchSource"]["admiralty_code"] is None
    assert by_source["NoSuchSource"]["grade_origin"] is None
