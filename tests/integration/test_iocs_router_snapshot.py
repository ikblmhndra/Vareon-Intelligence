"""Snapshot test `routers/iocs.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`, lihat docstring di situ buat penjelasan
`api_client`/`api_session`/matcher).

`first_seen`/`last_seen`/`added_at` (IOC + allowlist entry) SEMUA
`server_default=func.now()` -- non-deterministik lintas run, masuk
matcher. `fp-analytics` punya in-process cache module-level
(`fp_analytics._fp_analytics_cache`) yang idup lintas TEST dalam satu
proses pytest -- dipanggil `force=true` di sini biar gak numpang cache
basi dari test lain."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?ioc_id$": (int,),
        r"(.*\.)?first_seen$": (str,),
        r"(.*\.)?last_seen$": (str,),
        r"(.*\.)?valid_from$": (str,),
        r"(.*\.)?valid_until$": (str,),
        r"(.*\.)?added_at$": (str,),
    },
    regex=True,
    strict=False,
)


async def _seed_two_iocs(session: AsyncSession) -> None:
    repo = AsyncIndicatorRepo(session)
    await repo.upsert(
        type="ip", value="45.33.32.156", source_url="https://a.example/report", source_name="A"
    )
    await repo.upsert(
        type="domain", value="evil.example", source_url="https://b.example/report", source_name="B"
    )


async def test_list_iocs(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_two_iocs(api_session)
    resp = await api_client.get("/api/iocs", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_ioc_stats(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_two_iocs(api_session)
    resp = await api_client.get("/api/iocs/stats", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_ioc_fp_analytics(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_two_iocs(api_session)
    resp = await api_client.get(
        "/api/iocs/fp-analytics", headers=auth_header(), params={"force": "true"}
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_apply_fp_suggestions_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_two_iocs(api_session)
    resp = await api_client.post(
        "/api/iocs/fp-analytics/apply-suggestions", headers=auth_header(role="admin")
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_ioc_allowlist_list_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    # Skema test sudah di head: kosongkan seed migrasi 0.8.6 supaya daftar benar-benar kosong.
    await api_session.execute(text("DELETE FROM ioc_allowlist_entries"))
    resp = await api_client.get("/api/iocs/allowlist", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_ioc_allowlist_add(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.post(
        "/api/iocs/allowlist",
        headers=auth_header(role="admin"),
        json={"type": "ip", "value": "10.0.0.1"},
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_ioc_allowlist_remove(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    add_resp = await api_client.post(
        "/api/iocs/allowlist",
        headers=auth_header(role="admin"),
        json={"type": "ip", "value": "10.0.0.2"},
    )
    entry_id = add_resp.json()["id"]
    resp = await api_client.delete(
        f"/api/iocs/allowlist/{entry_id}", headers=auth_header(role="admin")
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_add_ioc_threat_actors(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_two_iocs(api_session)
    resp = await api_client.post(
        "/api/iocs/ip/45.33.32.156/threat-actors",
        headers=auth_header(),
        json={"threat_actors": ["Apt41"]},
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_remove_ioc_threat_actor(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_two_iocs(api_session)
    await api_client.post(
        "/api/iocs/ip/45.33.32.156/threat-actors",
        headers=auth_header(),
        json={"threat_actors": ["Apt41"]},
    )
    resp = await api_client.delete(
        "/api/iocs/ip/45.33.32.156/threat-actors/Apt41", headers=auth_header()
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_bulk_delete_iocs(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_two_iocs(api_session)
    iocs, _ = await AsyncIndicatorRepo(api_session).list_filtered(page=1, page_size=10)
    ids = [i.id for i in iocs]
    resp = await api_client.post(
        "/api/iocs/bulk-delete", headers=auth_header(role="admin"), json={"ids": ids}
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_delete_ioc_by_id(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_two_iocs(api_session)
    iocs, _ = await AsyncIndicatorRepo(api_session).list_filtered(page=1, page_size=10)
    resp = await api_client.delete(f"/api/iocs/{iocs[0].id}", headers=auth_header(role="admin"))
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_ioc_feedback(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_two_iocs(api_session)
    iocs, _ = await AsyncIndicatorRepo(api_session).list_filtered(
        ioc_type="ip", page=1, page_size=10
    )
    resp = await api_client.post(
        f"/api/iocs/{iocs[0].id}/feedback",
        headers=auth_header(),
        json={"verdict": "tp", "note": "confirmed malicious"},
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_ioc_ta_links_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_two_iocs(api_session)
    resp = await api_client.get("/api/iocs/ta-links/ip/45.33.32.156", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_ioc_detail(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_two_iocs(api_session)
    resp = await api_client.get("/api/iocs/ip/45.33.32.156", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_add_ioc_tags(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_two_iocs(api_session)
    resp = await api_client.post(
        "/api/iocs/ip/45.33.32.156/tags", headers=auth_header(), json={"tags": ["c2", "malware"]}
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot
