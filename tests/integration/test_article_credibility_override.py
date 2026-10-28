"""P6 5.1: `PUT /api/articles/{id}/credibility` -- override analis atas kredibilitas (1-6)."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_api.services.confidence import recompute_all_confidence
from cti_core.db.models import AuditLogEntry, SourceReliabilityEntry
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.assessment import apply_assessments_async
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> int:
    await AsyncClientRepo(session).ensure_default()
    today = datetime.date.today()
    session.add(
        SourceReliabilityEntry(
            source_name="OvSource",
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
    a = await AsyncArticleRepo(session).upsert(
        url="https://ov.example/1", title="Ov", source="OvSource", posted_on=today
    )
    await apply_assessments_async(session, [a.id])
    await session.commit()
    return a.id


async def test_override_set_survives_recompute_and_clears(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    aid = await _seed(api_session)
    url = f"/api/articles/{aid}/credibility"

    resp = await api_client.put(url, headers=auth_header(), json={"credibility": 5, "note": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["credibility"] == 5
    assert body["admiralty_code"] == "C5"
    article = await AsyncArticleRepo(api_session).get_by_id(aid)
    assert article is not None
    await api_session.refresh(article)
    assert article.overrides["credibility"] == 5
    stmt = select(AuditLogEntry).where(AuditLogEntry.action == "set_credibility")
    audit = (await api_session.execute(stmt)).scalars().all()
    assert len(audit) == 1
    assert audit[0].detail == {"credibility": 5, "note": "x"}

    await recompute_all_confidence(api_session)
    await api_session.commit()
    await api_session.refresh(article)
    assert article.credibility == 5

    resp = await api_client.put(url, headers=auth_header(), json={"credibility": None})
    assert resp.status_code == 200
    assert resp.json()["credibility"] == 4
    await api_session.refresh(article)
    assert "credibility" not in article.overrides


async def test_override_requires_permission_and_valid_range(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    aid = await _seed(api_session)
    url = f"/api/articles/{aid}/credibility"
    resp = await api_client.put(url, headers=auth_header(role="nobody"), json={"credibility": 2})
    assert resp.status_code == 403
    resp = await api_client.put(url, headers=auth_header(), json={"credibility": 7})
    assert resp.status_code == 422
    resp = await api_client.put(
        "/api/articles/99999999/credibility", headers=auth_header(), json={"credibility": 2}
    )
    assert resp.status_code == 404
