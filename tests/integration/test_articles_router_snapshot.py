"""Snapshot test `routers/articles.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`). Judul artikel dedup dipinjam VERBATIM
dari `test_dedup_service.py` (udah diverifikasi ngelewatin threshold
0.75 default)."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

# Dipin ke ISO week 39, 2026 (bukan `datetime.date.today()`) -- `week` di
# `_serialize()` (routers/articles.py) diturunin dari `posted_on`, jadi kalau
# ini ngikutin tanggal ASLI, snapshot `test_list_articles_dedup` bakal geser
# tiap minggu kalender berganti.
#
# JANGAN dipakai buat test yang lewat jendela relatif ke `date.today()`:
# `get_dedup_groups` cuma ngambil artikel 7 hari terakhir, jadi seed dengan
# tanggal pinned ini berhenti masuk jendela sejak 2026-10-01 dan
# `test_article_dedup_groups` merah (CI #11-#16). Test itu seed dengan tanggal
# asli -- snapshot-nya aman karena `posted_on` dinormalisasi jadi `str` dan
# respons dedup-groups gak punya field `week`/`month`.
_TODAY = datetime.date(2026, 9, 24)

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?posted_on$": (str,),
        # `compute_article_confidence` balikin `article_id` (bukan `id`
        # polos) -- pattern `id$` gak nangkep ini karena diawali `_`
        # bukan `.` (fullmatch, bukan search). Field lain yang berakhiran
        # "_id" tapi bukan int (mis. business key string) aman -- type
        # check `(int,)` bareng `strict=False` bikin non-match diam aja.
        r"(.*\.)?\w+_id$": (int,),
    },
    regex=True,
    strict=False,
)


async def _seed_dedup_articles(session: AsyncSession, posted_on: datetime.date = _TODAY) -> None:
    await AsyncClientRepo(session).ensure_default()
    repo = AsyncArticleRepo(session)
    await repo.upsert(
        url="https://a.example/apt41-1",
        title="Apt41 hits manufacturing sector hard",
        source="SourceA",
        posted_on=posted_on,
    )
    await repo.upsert(
        url="https://b.example/apt41-1",
        title="Apt41 hits manufacturing sector hard!",
        source="SourceB",
        posted_on=posted_on,
    )


async def _seed_one_article(session: AsyncSession) -> int:
    await AsyncClientRepo(session).ensure_default()
    a = await AsyncArticleRepo(session).upsert(
        url="https://example.com/apt41-solo",
        title="Apt41 breaches government network",
        source="gbhacker",
        posted_on=datetime.date(2026, 9, 1),
    )
    return a.id


async def test_article_dedup_groups(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_dedup_articles(api_session, posted_on=datetime.date.today())
    resp = await api_client.get("/api/articles/dedup-groups", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_list_articles(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_one_article(api_session)
    resp = await api_client.get("/api/articles", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_list_articles_dedup(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_dedup_articles(api_session)
    resp = await api_client.get("/api/articles", params={"dedup": "true"}, headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_list_filters(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_one_article(api_session)
    resp = await api_client.get("/api/filters", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_dashboard_stats(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    from cti_api.services import article_dashboard

    await _seed_one_article(api_session)
    # `get_dashboard_stats()` punya in-process cache module-level (900s
    # TTL, key dari `days`/tanggal) -- di-clear biar gak numpang hasil
    # basi dari test lain (pola sama kayak `cluster_service._CACHE`).
    article_dashboard._dashboard_cache.clear()
    resp = await api_client.get("/api/dashboard", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_compute_article_confidence(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    article_id = await _seed_one_article(api_session)
    resp = await api_client.post(f"/api/articles/{article_id}/confidence", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_recompute_confidence_all(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_one_article(api_session)
    resp = await api_client.post("/api/articles/confidence/recompute", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_get_article_by_id(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    article_id = await _seed_one_article(api_session)
    resp = await api_client.get(f"/api/articles/{article_id}", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)
