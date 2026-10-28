"""Pembaca indikator tidak boleh memuat yang dicabut (`revoked_at`), kecuali analitik FP
yang memang butuh riwayatnya. Postgres REAL."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services import stix as stix_service
from cti_core.db.models.indicator import Indicator, IndicatorFeedback
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_HASH = "a" * 64


async def _seed(session: AsyncSession) -> dict[str, Indicator]:
    """Satu aktif, satu dicabut, satu tersaring allowlist -- semuanya di artikel yang sama."""
    article = await AsyncArticleRepo(session).upsert(
        url="https://example.com/readers", title="t", source="s", posted_on=datetime.date.today()
    )
    repo = AsyncIndicatorRepo(session)
    rows: dict[str, Indicator] = {}
    for name, ioc_type, value in (
        ("active", "domain", "active.example.com"),
        ("revoked", "domain", "revoked.example.com"),
        ("suppressed", "domain", "suppressed.example.com"),
        ("hash", "sha256", _HASH),
    ):
        rows[name] = await repo.upsert(
            type=ioc_type,
            value=value,
            source_url="https://example.com/readers",
            source_name="s",
            article_id=article.id,
            suppression_reason="allowlist" if name == "suppressed" else None,
        )
    rows["revoked"].revoked_at = datetime.datetime.now(datetime.UTC)
    rows["article_id"] = article  # type: ignore[assignment]
    await session.flush()
    return rows


async def test_stats_exclude_revoked(async_db_session: AsyncSession) -> None:
    await _seed(async_db_session)
    stats = await AsyncIndicatorRepo(async_db_session).get_stats()
    assert stats["total"] == 2  # active + hash


async def test_campaign_rows_exclude_revoked(async_db_session: AsyncSession) -> None:
    rows = await _seed(async_db_session)
    got = await AsyncIndicatorRepo(async_db_session).list_by_article_ids([rows["article_id"].id])  # type: ignore[attr-defined]
    assert {i.value for i in got} == {"active.example.com", _HASH}


async def test_recap_first_seen_excludes_revoked(async_db_session: AsyncSession) -> None:
    await _seed(async_db_session)
    repo = AsyncIndicatorRepo(async_db_session)
    today = datetime.datetime.now(datetime.UTC).date()
    day = await repo.list_first_seen_on(today)
    assert {i.value for i in day} == {"active.example.com", _HASH}
    by_type = await repo.count_first_seen_by_type_between(
        today - datetime.timedelta(days=1), today + datetime.timedelta(days=1)
    )
    assert by_type == {"domain": 1, "sha256": 1}


async def test_enrichment_queue_excludes_revoked(async_db_session: AsyncSession) -> None:
    await _seed(async_db_session)
    got = await AsyncIndicatorRepo(async_db_session).list_needing_enrichment(
        provider="vt",
        types=["domain"],
        checked_before=datetime.datetime.now(datetime.UTC),
        limit=10,
    )
    assert [i.value for i in got] == ["active.example.com"]


async def test_fp_analytics_keeps_revoked(async_db_session: AsyncSession) -> None:
    rows = await _seed(async_db_session)
    repo = AsyncIndicatorRepo(async_db_session)
    async_db_session.add(
        IndicatorFeedback(indicator_id=rows["revoked"].id, verdict="fp", submitted_by="analyst")
    )
    await async_db_session.flush()
    got = await repo.list_with_feedback()
    assert [i.value for i in got] == ["revoked.example.com"]


async def test_stix_ioc_bundle(async_db_session: AsyncSession) -> None:
    await _seed(async_db_session)
    bundle = await stix_service.build_ioc_stix_bundle(async_db_session)
    inds = {o["name"]: o for o in bundle["objects"] if o["type"] == "indicator"}
    assert "domain: revoked.example.com" not in inds
    assert "domain: suppressed.example.com" not in inds

    active = inds["domain: active.example.com"]
    clear_id = stix_service.TLP_MARKING_IDS["clear"]
    assert active["valid_until"].endswith("Z")
    datetime.datetime.strptime(active["valid_until"], "%Y-%m-%dT%H:%M:%SZ")
    assert active["object_marking_refs"] == [clear_id]
    assert active["valid_from"].endswith("Z")

    marks = [o for o in bundle["objects"] if o["type"] == "marking-definition"]
    assert [m["id"] for m in marks] == [clear_id]
    assert marks[0]["name"] == "TLP:CLEAR"

    assert "valid_until" not in inds[f"sha256: {_HASH}"]
