"""IOC `auto_suppressed` (cocok allowlist) keluar dari export, statistik, daftar IOC campaign,
hitungan recap, dan antrean FP -- Postgres REAL (testcontainers). Detail IOC tetap bisa dibuka."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.models.indicator import Indicator
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_REASON = "allowlist:url_domain:gofile.io (infrastructure-abuse)"


async def _seed(session: AsyncSession) -> int:
    article = await AsyncArticleRepo(session).upsert(
        url="https://example.com/suppress-a",
        title="Suppression test article",
        source="S",
        posted_on=datetime.date.today(),
    )
    repo = AsyncIndicatorRepo(session)
    for value, reason in (("store1.gofile.io", _REASON), ("evil-c2.net", None)):
        await repo.upsert(
            type="domain",
            value=value,
            source_url="https://example.com/suppress-a",
            source_name="S",
            article_id=article.id,
            suppression_reason=reason,
        )
    return article.id


async def test_list_iocs_excludes_suppressed_unless_asked(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed(api_session)
    default = await api_client.get("/api/iocs", headers=auth_header())
    assert [i["value"] for i in default.json()["iocs"]] == ["evil-c2.net"]
    assert default.json()["total"] == 1

    both = await api_client.get("/api/iocs?include_suppressed=true", headers=auth_header())
    assert both.json()["total"] == 2


async def test_stats_and_stix_export_exclude_suppressed(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed(api_session)
    stats = await api_client.get("/api/iocs/stats", headers=auth_header())
    assert stats.json()["total"] == 1

    stix = await api_client.get("/api/stix/iocs", headers=auth_header())
    patterns = [o.get("pattern", "") for o in stix.json()["objects"] if o["type"] == "indicator"]
    assert len(patterns) == 1
    assert "evil-c2.net" in patterns[0]
    assert not any("gofile" in p for p in patterns)


async def test_detail_still_opens_suppressed_ioc(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed(api_session)
    resp = await api_client.get("/api/iocs/domain/store1.gofile.io", headers=auth_header())
    assert resp.status_code == 200


async def test_campaign_recap_and_fp_queue_exclude_suppressed(
    async_db_session: AsyncSession,
) -> None:
    article_id = await _seed(async_db_session)
    repo = AsyncIndicatorRepo(async_db_session)

    rows = await repo.list_by_article_ids([article_id])
    assert [r.value for r in rows] == ["evil-c2.net"]

    today = datetime.datetime.now(datetime.UTC).date()
    assert [r.value for r in await repo.list_first_seen_on(today)] == ["evil-c2.net"]
    assert await repo.count_first_seen_by_type_between(today, today) == {"domain": 1}

    for value in ("store1.gofile.io", "evil-c2.net"):
        ioc = await repo.get(type="domain", value=value)
        assert isinstance(ioc, Indicator)
        ioc.confidence_score = 55
    await async_db_session.flush()
    dash = AsyncDashboardRepo(async_db_session)
    assert [r.value for r in await dash.pending_fp_queue()] == ["evil-c2.net"]
    assert await dash.pending_fp_count() == 1
