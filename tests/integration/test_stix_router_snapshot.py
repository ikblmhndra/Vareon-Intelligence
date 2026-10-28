"""Snapshot test `routers/stix.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`).

Kebanyakan STIX object id pakai `uuid5(content)` (DETERMINISTIK, content-
hash) -- tapi `bundle--` dan `relationship--` id pakai `uuid4()` random
sungguhan, dan objek STIX bawa timestamp (`created`/`modified`/dst).
Matcher di sini normalisasi field "id" SECARA LUAS (semua jadi tipe str
doang, bukan value persis) daripada coba bedain per-posisi mana yang
deterministik vs random -- lebih aman buat snapshot SHAPE, walau
kehilangan verifikasi value uuid5 yang sebetulnya stabil."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (str, int),
        r"(.*\.)?created$": (str,),
        r"(.*\.)?modified$": (str,),
        r"(.*\.)?first_seen$": (str,),
        r"(.*\.)?last_seen$": (str,),
        r"(.*\.)?published$": (str,),
        # `_build_indicator()` (stix.py) juga nulis `valid_from`/
        # `x_last_seen` -- nama field beda dari `first_seen`/`last_seen`
        # polos di atas, sama-sama turunan tanggal "today" yang basi
        # tiap hari kalender maju.
        r"(.*\.)?valid_from$": (str,),
        r"(.*\.)?x_last_seen$": (str,),
        # `valid_until` = last_seen + TTL, jadi ikut maju tiap hari.
        r"(.*\.)?valid_until$": (str,),
    },
    regex=True,
    strict=False,
)


async def _seed_article(session: AsyncSession) -> int:
    await AsyncClientRepo(session).ensure_default()
    repo = AsyncArticleRepo(session)
    a = await repo.upsert(
        url="https://example.com/apt41-stix",
        title="APT41 breaches government network",
        source="gbhacker",
        posted_on=datetime.date(2026, 9, 1),
    )
    await repo.set_enrichment(a, threat_actors=["Apt41"], ttps=[("T1566", "T1566 Phishing")])
    return a.id


async def test_export_article_stix(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    article_id = await _seed_article(api_session)
    resp = await api_client.get(f"/api/stix/article/{article_id}", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_export_ta_stix_not_found(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/stix/ta/UnknownActor", headers=auth_header())
    assert resp.status_code == 404
    assert resp.json() == snapshot


async def test_export_ioc_stix(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await AsyncIndicatorRepo(api_session).upsert(
        type="domain", value="evil.example", source_url="https://a.example", source_name="A"
    )
    resp = await api_client.get("/api/stix/iocs", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_export_pir_stix_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/stix/pirs", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)
