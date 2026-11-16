"""Snapshot test `routers/intelligence.py` -- Fase 7.6 (lanjutan pola
pilot `test_cve_router_snapshot.py`).

Judul artikel dipinjam VERBATIM dari `test_cluster_service.py`
(Pipeline 1, threshold 0.35)/`test_campaign_service.py` (Pipeline 2,
threshold 0.75 FIXED) -- keduanya udah diverifikasi lewat percobaan
`TfidfVectorizer` langsung pas Fase 7.4 Grup A, jadi gak perlu re-derive
similarity di sini. `cluster_service._CACHE` (900s in-process TTL) di-
clear manual sebelum tiap panggilan `/clusters`, sama pola kayak test
service-layer yang udah ada -- endpoint ini sendiri gak expose parameter
buat bypass cache."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_api.services import cluster as cluster_service
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_TODAY = datetime.date.today()

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?posted_on$": (str,),
        r"(.*\.)?first_date$": (str,),
        r"(.*\.)?last_date$": (str,),
        r"(.*\.)?date$": (str,),
        r"(.*\.)?generated_at$": (str,),
        r"(.*\.)?first_seen$": (str,),
        r"(.*\.)?last_seen$": (str,),
        # list of raw article-id ints (`member_article_ids: [8, 7]`) --
        # path per elemen berakhir di angka index, bukan "id" literal,
        # jadi butuh pattern sendiri (beda dari field skalar `id`).
        r"(.*\.)?member_article_ids\.\d+$": (int,),
        r"daily\.dates\.\d+$": (str,),
    },
    regex=True,
    strict=False,
)

_PIPELINE1_TITLES = [
    "Apt41 threat group breaches manufacturing sector networks United",
    "Apt41 threat group breaches manufacturing sector networks Europe",
    "Apt41 threat group breaches manufacturing sector networks Japan",
]

_PIPELINE2_TITLES = [
    "Apt41 threat group breaches manufacturing networks alpha",
    "Apt41 threat group breaches manufacturing networks beta",
]


async def _seed_pipeline1_articles(session: AsyncSession) -> None:
    await AsyncClientRepo(session).ensure_default()
    repo = AsyncArticleRepo(session)
    for i, title in enumerate(_PIPELINE1_TITLES):
        await repo.upsert(
            url=f"https://example.com/p1-apt41-{i}",
            title=title,
            source=f"Source{i}",
            posted_on=_TODAY,
        )


async def _seed_pipeline2_articles(session: AsyncSession) -> None:
    await AsyncClientRepo(session).ensure_default()
    repo = AsyncArticleRepo(session)
    for i, title in enumerate(_PIPELINE2_TITLES):
        a = await repo.upsert(
            url=f"https://example.com/p2-apt41-{i}",
            title=title,
            source=f"Source{i}",
            posted_on=_TODAY,
        )
        await repo.set_enrichment(a, threat_actors=["Apt41"])


async def test_early_warning(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/spikes", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_risk_matrix(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    from cti_api.services import risk_matrix as risk_matrix_service

    # Cache module-level (900s TTL, key `days|compare_days`) -- sama
    # alasan kayak `cluster_service._CACHE`/`article_dashboard._dashboard_
    # cache`, di-clear biar gak numpang hasil basi dari test lain.
    risk_matrix_service._CACHE.clear()
    resp = await api_client.get("/api/intelligence/risk-matrix", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_source_scores(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_pipeline1_articles(api_session)
    resp = await api_client.get("/api/source-scores", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_article_clusters(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_pipeline1_articles(api_session)
    cluster_service._CACHE.clear()
    resp = await api_client.get("/api/clusters", headers=auth_header(), params={"days": 30})
    assert resp.status_code == 200
    body = resp.json()
    for c in body["clusters"]:
        # `sources` dibangun dari `set` di service-nya (unik doang, gak
        # di-sort) -- urutan iterasi set string di Python di-randomize per
        # proses (`PYTHONHASHSEED`), jadi disortir dulu di sini biar
        # snapshot stabil lintas run. Normalisasi test, bukan ubah service.
        c["sources"] = sorted(c["sources"])
    assert body == snapshot(matcher=_NORMALIZE)


async def test_recent_campaigns(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_pipeline2_articles(api_session)
    resp = await api_client.get(
        "/api/clusters/recent", headers=auth_header(), params={"days": 7, "min_size": 2}
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_campaign_evolution(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_pipeline1_articles(api_session)
    cluster_service._CACHE.clear()
    await cluster_service.get_clusters(api_session, days=30)
    resp = await api_client.get("/api/clusters/evolution", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_cluster_trends(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_pipeline1_articles(api_session)
    cluster_service._CACHE.clear()
    clusters = await cluster_service.get_clusters(api_session, days=30)
    cluster_id = clusters[0]["cluster_id"]
    resp = await api_client.get(f"/api/clusters/{cluster_id}/trends", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_geopolitical_summary(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_pipeline2_articles(api_session)
    resp = await api_client.get("/api/intelligence/geopolitical", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)
