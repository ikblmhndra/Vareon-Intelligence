"""Grade bawaan sumber dan skor confidence deterministik -- Postgres REAL (testcontainers).
Rilis 0.8.6, spec P2 5.1 dan 5.2."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_api.services import confidence as svc
from cti_core.db.models.article import Article
from cti_core.db.models.source_reliability import SourceReliabilityEntry
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.source_reliability import AsyncSourceReliabilityRepo
from cti_enrich.routing import RoutingResult
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.extract_ttps import Technique, TtpResult
from cti_enrich.stages.persist import persist
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


@pytest.mark.asyncio
async def test_ensure_defaults_respects_analyst_rows(async_db_session: AsyncSession) -> None:
    repo = AsyncSourceReliabilityRepo(async_db_session)
    await repo.add_entry(
        source_name="Mandiant",
        analyst_name="analyst1",
        reliability_grade="A",
        credibility_code="1",
        notes="",
    )

    inserted = await repo.ensure_defaults(
        {"mandiant": "vendor_research", "BleepingComputer": "news"}
    )

    assert inserted == ["BleepingComputer"]
    mandiant = await repo.get_by_name_ci("Mandiant")
    assert mandiant is not None
    assert (mandiant.admiralty_code, mandiant.origin, mandiant.analyst_name) == (
        "A1",
        "analyst",
        "analyst1",
    )
    bleeping = await repo.get_by_name_ci("BleepingComputer")
    assert bleeping is not None
    assert (bleeping.admiralty_code, bleeping.origin, bleeping.analyst_name) == (
        "C3",
        "default",
        "system",
    )
    assert await repo.ensure_defaults({"BLEEPINGCOMPUTER": "social"}) == []


def _persist(session: Session, url: str, source: str, ttps: int, actors: list[str]) -> Article:
    return persist(
        session=session,
        url=url,
        title="t",
        source=source,
        scraper_id=None,
        posted_on=None,
        classify_result=ClassifyResult(related_cyber=True, confidence=0.99),
        score_result=None,
        routing_result=RoutingResult(
            news_type="General", alert_topics=[], msg_data="", threat_actors=actors
        ),
        ttp_result=TtpResult(
            has_techniques=bool(ttps),
            techniques=[Technique(f"T{1000 + i}", f"Tech {i}") for i in range(ttps)],
        ),
        ioc_data={},
        c2_indicator=False,
    )


def test_persist_confidence_from_grade(db_session: Session) -> None:
    today = datetime.date.today()
    db_session.add(
        SourceReliabilityEntry(
            source_name="Graded Src",
            analyst_name="a",
            reliability_grade="B",
            credibility_code="2",
            admiralty_code="B2",
            notes="",
            added_date=today,
            last_updated=today,
            origin="analyst",
        )
    )
    db_session.flush()

    graded = _persist(db_session, "https://n.example/graded", "graded src", 1, [])
    ungraded = _persist(db_session, "https://n.example/ungraded", "Nobody", 0, [])

    # B2: base 80 + 1 TTP * 5 = 85 (self-rating LLM 0.99 tidak dipakai); tanpa grade: 50
    assert graded.confidence_score == 85
    assert ungraded.confidence_score == 50


@pytest.mark.asyncio
async def test_recompute_source_writes_column_not_overrides(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncArticleRepo(async_db_session)
    sr = AsyncSourceReliabilityRepo(async_db_session)
    await sr.ensure_defaults({"Src One": "kev", "Other": "social"})
    plain = await repo.upsert(url="https://e.example/1", title="1", source="src one")
    pinned = await repo.upsert(url="https://e.example/2", title="2", source="SRC ONE")
    other = await repo.upsert(url="https://e.example/3", title="3", source="Other")
    await repo.set_overrides(pinned, confidence_score=7)
    plain_id, pinned_id, other_id = plain.id, pinned.id, other.id

    result = await svc.recompute_all_confidence(async_db_session, source_name="Src One")
    assert result == {"updated": 1}

    async_db_session.expire_all()
    plain_row = await repo.get_by_id(plain_id)
    pinned_row = await repo.get_by_id(pinned_id)
    other_row = await repo.get_by_id(other_id)
    assert plain_row is not None and pinned_row is not None and other_row is not None
    assert plain_row.confidence_score == 100  # A1
    assert "confidence_score" not in plain_row.overrides
    assert pinned_row.confidence_score is None  # override analis menang, kolom tidak disentuh
    assert pinned_row.overrides["confidence_score"] == 7
    assert other_row.confidence_score is None  # sumber lain tidak ikut


@pytest.mark.asyncio
async def test_editing_default_row_marks_analyst(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(
        "cti_api.routers.source_reliability.send_recompute_source", lambda name: sent.append(name)
    )
    await AsyncSourceReliabilityRepo(api_session).ensure_defaults({"Edit Me": "news"})
    repo = AsyncSourceReliabilityRepo(api_session)
    entry = await repo.get_by_name_ci("Edit Me")
    assert entry is not None

    listed = await api_client.get("/api/sr/entries", headers=auth_header())
    assert [(e["source_name"], e["origin"]) for e in listed.json()["entries"]] == [
        ("Edit Me", "default")
    ]

    resp = await api_client.put(
        f"/api/sr/entries/{entry.id}",
        json={"analyst_name": "bob", "reliability_grade": "A", "credibility_code": "2"},
        headers=auth_header(),
    )
    assert resp.json() == {"success": True}
    assert sent == ["Edit Me"]

    listed = await api_client.get("/api/sr/entries", headers=auth_header())
    row = listed.json()["entries"][0]
    assert (row["origin"], row["admiralty_code"], row["analyst_name"]) == ("analyst", "A2", "bob")
