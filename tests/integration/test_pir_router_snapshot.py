"""Snapshot test `routers/pir.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`).

`posted_on` di seed pakai TANGGAL RELATIF (`today() - N hari`, sama pola
kayak `test_pir_query.py`) biar klasifikasi "recent coverage"/`is_gap`
stabil selamanya -- konsekuensinya nilai literal `posted_on` berubah
tiap hari, jadi masuk matcher (bukan snapshot value-nya, cuma shape)."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?created_at$": (str,),
        r"(.*\.)?updated_at$": (str,),
        r"(.*\.)?posted_on$": (str,),
        # tanggal artikel terbaru yang cocok = `today() - 2 hari` dari seed
        r"(.*\.)?last_match$": (str,),
        r"(.*\.)?exported_at$": (str,),
        # `_article_export_dict()` nulis `"_id": str(article.id)` -- key
        # "_id" (bukan "id") dan nilainya STRING (bukan int, beda dari
        # `id` biasa), jadi pattern+type terpisah.
        r"(.*\.)?_id$": (str,),
        # `pir_id` (note endpoints) -- field lain yang berakhiran "_id"
        # tapi int, sama alasan kayak `article_id` di
        # `test_articles_router_snapshot.py`.
        r"(.*\.)?\w+_id$": (int,),
    },
    regex=True,
    strict=False,
)


async def _seed_article(session: AsyncSession) -> None:
    await AsyncClientRepo(session).ensure_default()
    recent = datetime.date.today() - datetime.timedelta(days=2)
    a = await AsyncArticleRepo(session).upsert(
        url="https://example.com/apt41-recent",
        title="APT41 hits government network",
        source="gbhacker",
        posted_on=recent,
        news_type="apac",
    )
    await AsyncArticleRepo(session).set_enrichment(a, threat_actors=["Apt41"])


async def _seed_pir(session: AsyncSession) -> int:
    repo = AsyncPIRRepo(session)
    pir = await repo.create(
        {
            "title": "Track APT41",
            "description": "Monitor APT41 activity",
            "priority": "P1",
            "owner": "analyst1",
            "criteria": {"threat_actors": ["Apt41"]},
        },
        client_id="default",
    )
    return pir.id


async def test_pir_options(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_article(api_session)
    resp = await api_client.get("/api/pir/options", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_get_pirs(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_article(api_session)
    await _seed_pir(api_session)
    resp = await api_client.get("/api/pir", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_pir_articles(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_article(api_session)
    pir_id = await _seed_pir(api_session)
    resp = await api_client.get(f"/api/pir/{pir_id}/articles", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_pir_get_note_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    pir_id = await _seed_pir(api_session)
    resp = await api_client.get(
        f"/api/pir/{pir_id}/note",
        params={"url": "https://example.com/apt41-recent"},
        headers=auth_header(),
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_pir_save_note(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    pir_id = await _seed_pir(api_session)
    resp = await api_client.put(
        f"/api/pir/{pir_id}/note",
        headers=auth_header(),
        json={
            "url": "https://example.com/apt41-recent",
            "note": "confirmed real campaign",
            "analyst": "analyst1",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_pir_export(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_article(api_session)
    pir_id = await _seed_pir(api_session)
    resp = await api_client.get(f"/api/pir/{pir_id}/export", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_pir_export_docx(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_article(api_session)
    pir_id = await _seed_pir(api_session)
    resp = await api_client.get(f"/api/pir/{pir_id}/export/docx", headers=auth_header())
    assert resp.status_code == 200
    assert resp.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert len(resp.content) > 0


async def test_post_pir(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.post(
        "/api/pir",
        headers=auth_header(),
        json={
            "title": "Track Lazarus",
            "priority": "P2",
            "criteria": {"threat_actors": ["Lazarus"]},
        },
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_put_pir(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    pir_id = await _seed_pir(api_session)
    resp = await api_client.put(
        f"/api/pir/{pir_id}", headers=auth_header(), json={"status": "archived"}
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_remove_pir(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    pir_id = await _seed_pir(api_session)
    resp = await api_client.delete(f"/api/pir/{pir_id}", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot
