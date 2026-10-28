"""Integration test antrean review grade sumber (P6 spec 5.3): `GET /api/sr/review`,
`POST /api/sr/entries/{id}/confirm`, dan PUT tanpa `credibility_code` -- Postgres REAL."""

from __future__ import annotations

import datetime
import hashlib
from collections.abc import Callable
from typing import Any

import pytest
from cti_core.db.models.article import Article, RejectedArticle
from cti_core.db.models.article_cve import ArticleCve
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.indicator import Indicator, IndicatorFeedback, IndicatorSource
from cti_core.db.models.source_reliability import SourceReliabilityEntry
from cti_core.db.models.story import Story
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_NOW = datetime.datetime.now(datetime.UTC)
_OLD = _NOW - datetime.timedelta(days=45)
_TODAY = _NOW.date()


def _sr(name: str, grade: str, origin: str = "default") -> SourceReliabilityEntry:
    return SourceReliabilityEntry(
        source_name=name,
        analyst_name="system" if origin == "default" else "analyst1",
        reliability_grade=grade,
        credibility_code="3",
        admiralty_code=f"{grade}3",
        notes="",
        added_date=_TODAY,
        last_updated=_TODAY,
        origin=origin,
        content_kind="news",
    )


def _article(url: str, source: str, at: datetime.datetime = _NOW, **kw: Any) -> Article:
    return Article(
        url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        title=f"title {url}",
        source=source,
        first_seen_at=at,
        last_seen_at=at,
        **kw,
    )


def _rejected(url: str, source: str, reason: str, at: datetime.datetime = _NOW) -> RejectedArticle:
    return RejectedArticle(
        url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        title=url,
        source=source,
        reason=reason,
        rejected_at=at,
    )


async def _seed(s: AsyncSession) -> dict[str, SourceReliabilityEntry]:
    rows = {
        "low": _sr("RvLowSrc", "B"),
        "lead": _sr("RvLeadSrc", "C"),
        "analyst": _sr("RvAnalystSrc", "B", origin="analyst"),
    }
    s.add_all(rows.values())

    # RvLowSrc: 16 artikel (1 dengan CVE), 9 ditolak off-topic, 3 gagal enrichment (diabaikan),
    # plus artikel/penolakan lama di luar jendela 30 hari. Nama sumber beda huruf sengaja.
    low = [_article(f"https://rv.example/low/{i}", "rvlowsrc") for i in range(16)]
    low.append(_article("https://rv.example/low/old", "RvLowSrc", at=_OLD))
    s.add_all(low)
    for i in range(9):
        s.add(_rejected(f"https://rv.example/rej/{i}", "RvLowSrc", "marketing"))
    for i in range(3):
        s.add(_rejected(f"https://rv.example/fail/{i}", "RvLowSrc", "[enrichment_failed] boom"))
    s.add(_rejected("https://rv.example/rej/old", "RvLowSrc", "marketing", at=_OLD))

    # RvLeadSrc: 10 artikel; 6 story multi-sumber, 4 di antaranya dipimpin sumber ini.
    lead = [_article(f"https://rv.example/lead/{i}", "RvLeadSrc") for i in range(10)]
    other = [_article(f"https://rv.example/other/{i}", "RvOtherSrc") for i in range(6)]
    analyst = [_article(f"https://rv.example/an/{i}", "RvAnalystSrc") for i in range(12)]
    s.add_all([*lead, *other, *analyst])
    await s.flush()

    s.add(ArticleCve(article_id=low[0].id, cve_id="CVE-2026-0001"))
    for i in range(6):
        story = Story(
            title=f"story {i}", lead_source="x", first_seen_at=_NOW, last_seen_at=_NOW,
            source_count=2, article_count=2,
            lead_article_id=lead[i].id if i < 4 else other[i].id,
        )  # fmt: skip
        s.add(story)
        await s.flush()
        lead[i].story_id = story.id
        other[i].story_id = story.id

    # IOC: dilaporkan pertama oleh RvLowSrc (1 FP + 1 TP); IOC lain pertama oleh RvOtherSrc
    # (verdict-nya tidak dihitung ke RvLowSrc walau RvLowSrc ikut melaporkan belakangan).
    ioc_a = Indicator(type="ip", value="10.9.0.1")
    ioc_b = Indicator(type="ip", value="10.9.0.2")
    s.add_all([ioc_a, ioc_b])
    await s.flush()
    s.add_all(
        [
            IndicatorSource(
                indicator_id=ioc_a.id, url="u", source_name="RvLowSrc", first_seen_at=_OLD
            ),
            IndicatorSource(
                indicator_id=ioc_b.id, url="u", source_name="RvOtherSrc", first_seen_at=_OLD
            ),
            IndicatorSource(
                indicator_id=ioc_b.id, url="u", source_name="RvLowSrc", first_seen_at=_NOW
            ),
            IndicatorFeedback(indicator_id=ioc_a.id, verdict="fp", submitted_by="a"),
            IndicatorFeedback(indicator_id=ioc_a.id, verdict="tp", submitted_by="a"),
            IndicatorFeedback(indicator_id=ioc_b.id, verdict="fp", submitted_by="a"),
        ]
    )
    await s.flush()
    return rows


async def test_review_stats_and_suggestions(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed(api_session)
    resp = await api_client.get("/api/sr/review", headers=auth_header())
    assert resp.status_code == 200
    items = {i["entry"]["source_name"]: i for i in resp.json()["items"]}

    assert "RvAnalystSrc" not in items

    low = items["RvLowSrc"]
    assert {k: low[k] for k in ("articles", "rejected", "artefact_articles")} == {
        "articles": 16,
        "rejected": 9,
        "artefact_articles": 1,
    }
    assert (low["ioc_verdicts"], low["ioc_fp"]) == (2, 1)
    assert low["rejected_pct"] == pytest.approx(36.0)
    assert low["artefact_pct"] == pytest.approx(6.25)
    assert low["ioc_fp_pct"] == pytest.approx(50.0)
    assert (low["suggested_grade"], low["suggestion_reasons"]) == ("C", ["off_topic"])

    lead = items["RvLeadSrc"]
    assert (lead["multi_source_stories"], lead["lead_count"]) == (6, 4)
    assert (lead["suggested_grade"], lead["suggestion_reasons"]) == ("B", ["reports_first"])
    assert lead["entry"]["content_kind"] == "news"


async def test_review_requires_manage_sources(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/sr/review", headers=auth_header(role="analyst"))
    assert resp.status_code == 403


async def test_confirm_without_grade(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []
    monkeypatch.setattr("cti_api.routers.source_reliability.send_recompute_source", sent.append)
    rows = await _seed(api_session)
    entry_id = rows["low"].id

    resp = await api_client.post(
        f"/api/sr/entries/{entry_id}/confirm", headers=auth_header(username="ana"), json={}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (body["origin"], body["analyst_name"], body["reliability_grade"]) == (
        "analyst",
        "ana",
        "B",
    )
    assert sent == []
    audit = (
        await api_session.execute(
            select(AuditLogEntry).where(AuditLogEntry.action == "confirm_source_rating")
        )
    ).scalar_one()
    assert audit.username == "ana"


async def test_confirm_with_new_grade_enqueues_once(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []
    monkeypatch.setattr("cti_api.routers.source_reliability.send_recompute_source", sent.append)
    rows = await _seed(api_session)
    entry_id = rows["low"].id

    resp = await api_client.post(
        f"/api/sr/entries/{entry_id}/confirm",
        headers=auth_header(),
        json={"reliability_grade": "c"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (body["reliability_grade"], body["admiralty_code"], body["origin"]) == (
        "C",
        "C3",
        "analyst",
    )
    assert sent == ["RvLowSrc"]


async def test_confirm_missing_entry_404(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.post("/api/sr/entries/999999/confirm", headers=auth_header(), json={})
    assert resp.status_code == 404


async def test_update_without_credibility_keeps_code(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    rows = await _seed(api_session)
    entry = rows["lead"]
    resp = await api_client.put(
        f"/api/sr/entries/{entry.id}",
        headers=auth_header(),
        json={"analyst_name": "ana", "reliability_grade": "B", "notes": ""},
    )
    assert resp.status_code == 200
    await api_session.refresh(entry)
    assert (entry.reliability_grade, entry.credibility_code, entry.admiralty_code) == (
        "B",
        "3",
        "B3",
    )


async def test_add_without_credibility_writes_6(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.post(
        "/api/sr/entries",
        headers=auth_header(),
        json={"source_name": "RvNewSrc", "analyst_name": "ana", "reliability_grade": "b"},
    )
    assert resp.status_code == 200
    entry = resp.json()["entry"]
    assert (entry["credibility_code"], entry["admiralty_code"]) == ("6", "B6")
