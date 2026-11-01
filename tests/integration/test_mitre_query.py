"""Integration test `AsyncMitreHeatmapRepo` -- Postgres REAL
(testcontainers). Fase 7.3 (router `mitre`, Bagian 3)."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.mitre import AsyncMitreHeatmapRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _seed(article_repo: AsyncArticleRepo) -> None:
    recent = datetime.date.today() - datetime.timedelta(days=5)
    old = datetime.date.today() - datetime.timedelta(days=200)

    a1 = await article_repo.upsert(
        url="https://example.com/apt41-t1059", title="a1", source="s", posted_on=recent
    )
    await article_repo.set_enrichment(
        a1,
        threat_actors=["Apt41"],
        industries=["Government"],
        ttps=[("T1059", "Command Scripting")],
    )

    a2 = await article_repo.upsert(
        url="https://example.com/apt41-t1071", title="a2", source="s", posted_on=recent
    )
    await article_repo.set_enrichment(
        a2,
        threat_actors=["Apt41"],
        industries=["Government"],
        ttps=[("T1071", "App Layer Protocol")],
    )

    a3 = await article_repo.upsert(
        url="https://example.com/turla-t1059", title="a3", source="s", posted_on=recent
    )
    await article_repo.set_enrichment(
        a3, threat_actors=["Turla"], industries=["Finance"], ttps=[("T1059", "Command Scripting")]
    )

    a4 = await article_repo.upsert(
        url="https://example.com/old-apt41", title="a4 outside window", source="s", posted_on=old
    )
    await article_repo.set_enrichment(
        a4, threat_actors=["Apt41"], ttps=[("T1059", "Command Scripting")]
    )


async def test_get_heatmap_by_ta(async_db_session: AsyncSession) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    await _seed(article_repo)
    repo = AsyncMitreHeatmapRepo(async_db_session)

    heatmap = await repo.get_heatmap(view="ta", days=90, top_rows=5, top_ttps=5)
    assert "Apt41" in heatmap["rows"]
    assert "Turla" in heatmap["rows"]
    ttp_ids = [t["id"] for t in heatmap["ttps"]]
    assert "T1059" in ttp_ids
    assert "T1071" in ttp_ids

    apt41_idx = heatmap["rows"].index("Apt41")
    t1059_idx = ttp_ids.index("T1059")
    t1071_idx = ttp_ids.index("T1071")
    # a4 di luar window 90 hari -- gak boleh ikut ke-hitung
    assert heatmap["matrix"][apt41_idx][t1059_idx] == 1
    assert heatmap["matrix"][apt41_idx][t1071_idx] == 1


async def test_get_heatmap_by_industry(async_db_session: AsyncSession) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    await _seed(article_repo)
    repo = AsyncMitreHeatmapRepo(async_db_session)

    heatmap = await repo.get_heatmap(view="industry", days=90, top_rows=5, top_ttps=5)
    assert set(heatmap["rows"]) == {"Government", "Finance"}


async def test_get_heatmap_empty_returns_empty_shape(async_db_session: AsyncSession) -> None:
    repo = AsyncMitreHeatmapRepo(async_db_session)
    heatmap = await repo.get_heatmap(view="ta", days=90)
    assert heatmap == {"rows": [], "row_ids": [], "ttps": [], "matrix": [], "max_val": 0}


async def test_get_navigator_layer_scores_relative_to_max(async_db_session: AsyncSession) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    await _seed(article_repo)
    repo = AsyncMitreHeatmapRepo(async_db_session)

    layer = await repo.get_navigator_layer(view="ta", days=90)
    by_id = {t["techniqueID"]: t for t in layer["techniques"]}
    assert by_id["T1059"]["score"] == 100  # observed 2x (a1 + a3), max
    assert by_id["T1071"]["score"] == 50  # observed 1x


async def test_get_ttp_articles_filters_by_row_and_ttp(async_db_session: AsyncSession) -> None:
    article_repo = AsyncArticleRepo(async_db_session)
    await _seed(article_repo)
    repo = AsyncMitreHeatmapRepo(async_db_session)

    articles, total = await repo.get_ttp_articles(ttp_id="T1059", row="Apt41", view="ta", days=90)
    assert total == 1
    assert articles[0].url == "https://example.com/apt41-t1059"
