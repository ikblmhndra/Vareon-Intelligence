"""`GET /api/articles` membawa kode Admiralty + asal grade source (Task 9, P2 cheap wins)."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.models import SourceReliabilityEntry
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.assessment import apply_assessments_async
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
    # P6: kode Admiralty kini milik artikel (belum dinilai -> None); asal grade source tetap
    assert by_source["gradedsource"]["admiralty_code"] is None
    assert by_source["gradedsource"]["grade_origin"] == "default"
    assert by_source["NoSuchSource"]["admiralty_code"] is None
    assert by_source["NoSuchSource"]["grade_origin"] is None


async def test_article_carries_own_assessment(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """P6: `admiralty_code` sekarang kode ARTIKEL (grade + kredibilitas), `grade_origin` tetap
    asal grade source; artikel yang belum dinilai -> `None`."""
    await AsyncClientRepo(api_session).ensure_default()
    today = datetime.date.today()
    api_session.add(
        SourceReliabilityEntry(
            source_name="AssessedSource",
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
    a = await repo.upsert(
        url="https://a.example/1", title="Assessed", source="AssessedSource", posted_on=today
    )
    b = await repo.upsert(
        url="https://b.example/1", title="Fresh", source="AssessedSource", posted_on=today
    )
    await apply_assessments_async(api_session, [a.id])
    await api_session.commit()

    resp = await api_client.get("/api/articles", headers=auth_header())
    by_id = {x["id"]: x for x in resp.json()["articles"]}
    assessed = by_id[a.id]
    assert assessed["admiralty_code"] == "C4"
    assert assessed["reliability_grade"] == "C"
    assert assessed["credibility"] == 4
    assert assessed["priority_score"] == 40
    assert assessed["score_reasons"]["credibility"] == ["single_aggregator"]
    assert assessed["grade_origin"] == "default"
    fresh = by_id[b.id]
    assert fresh["admiralty_code"] is None
    assert fresh["credibility"] is None
    assert fresh["score_reasons"] == {"credibility": [], "priority": []}


async def test_article_detail_carries_source_grade_origin(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """`GET /api/articles/{id}` (modal artikel) harus membawa `grade_origin` seperti endpoint
    list; dulu `_serialize` dipanggil tanpa rating sehingga selalu `None` di sini."""
    await AsyncClientRepo(api_session).ensure_default()
    today = datetime.date.today()
    api_session.add(
        SourceReliabilityEntry(
            source_name="DetailSource",
            analyst_name="analyst",
            reliability_grade="A",
            credibility_code="1",
            admiralty_code="A1",
            notes="",
            added_date=today,
            last_updated=today,
            origin="analyst",
        )
    )
    repo = AsyncArticleRepo(api_session)
    graded = await repo.upsert(
        url="https://d.example/1", title="Graded detail", source="detailsource", posted_on=today
    )
    ungraded = await repo.upsert(
        url="https://d.example/2", title="Ungraded detail", source="NoRow", posted_on=today
    )
    await api_session.commit()

    resp = await api_client.get(f"/api/articles/{graded.id}", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json()["grade_origin"] == "analyst"
    resp = await api_client.get(f"/api/articles/{ungraded.id}", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json()["grade_origin"] is None
