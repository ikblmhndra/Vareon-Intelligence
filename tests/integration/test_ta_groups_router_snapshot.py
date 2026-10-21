"""Snapshot test `routers/ta_groups.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`).

`POST /profile/generate` manggil LLM asli (`ta_profile._call_llm`) --
di-mock, sama titik yang dipakai `ta_profile.py` sendiri
(`cti_api.services.ta_profile`, bukan `cti_core.llm.client` -- yang
dipatch di sini fungsi INTERNAL modul servicenya, bukan client-nya)."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from cti_api.services import ta_profile as ta_profile_service
from cti_core.db.repositories import ta as ta_repo
from cti_core.db.repositories.ta import AsyncTARepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?added_date$": (str,),
        r"(.*\.)?_generated_at$": (str,),
    },
    regex=True,
    strict=False,
)


async def _seed_group(session: AsyncSession) -> None:
    await AsyncTARepo(session).add_group("APT41")


async def test_get_ta_groups(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_group(api_session)
    resp = await api_client.get("/api/ta/groups", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_ta_stats(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_group(api_session)
    resp = await api_client.get("/api/ta/stats", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_post_ta_group(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.post("/api/ta/groups", headers=auth_header(), json={"name": "Lazarus"})
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_delete_ta_group(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_group(api_session)
    groups, _ = await AsyncTARepo(api_session).list_groups()
    resp = await api_client.delete(
        f"/api/ta/groups/{groups[0].id}",
        headers=auth_header(),
        params={"group_name": "APT41"},
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_get_whitelist_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/ta/whitelist", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_restore_from_whitelist(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_group(api_session)
    groups, _ = await AsyncTARepo(api_session).list_groups()
    await AsyncTARepo(api_session).delete_group(groups[0].id, "APT41")
    resp = await api_client.delete("/api/ta/whitelist/APT41", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_get_ta_watchlist_names_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/ta/watchlist-names", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_get_ta_watchlist_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/ta/watchlist", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_get_actor_timeline(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Jendela `months` 24 bulan dihitung dari "hari ini" -- dibekukan biar
    # snapshot gak basi tiap ganti bulan.
    monkeypatch.setattr(ta_repo, "_today", lambda: datetime.date(2026, 9, 15))
    resp = await api_client.get("/api/ta/APT41/timeline", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_post_ta_watchlist(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.post(
        "/api/ta/watchlist", headers=auth_header(), json={"name": "Lazarus"}
    )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_delete_ta_watchlist(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await api_client.post("/api/ta/watchlist", headers=auth_header(), json={"name": "Lazarus"})
    resp = await api_client.delete("/api/ta/watchlist/Lazarus", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_post_ta_profile_generate(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    fake_profile = {
        "identity": {"actor_type": "state-sponsored", "sponsoring_nation": "China"},
        "capability_assessment": {"sophistication_level": "nation-state"},
    }
    with patch.object(ta_profile_service, "_call_llm", MagicMock(return_value=fake_profile)):
        resp = await api_client.post(
            "/api/ta/profile/generate", headers=auth_header(), json={"name": "APT41"}
        )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_get_ta_profile_endpoint_not_found(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/ta/profile/Unknown", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_watchlist_navigator_layer_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/ta/watchlist/navigator-layer", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_watchlist_reads_ignore_a_foreign_client_header(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """Audit 2026-10-21: `X-Client-ID` milik client lain dulu diterima apa adanya."""
    await AsyncTARepo(api_session).add_to_watchlist("Lazarus", "default")
    own = await api_client.get("/api/ta/watchlist-names", headers=auth_header())
    assert own.json() == {"names": ["Lazarus"]}  # kontrol: seed-nya memang terlihat

    outsider = {**auth_header(role="analyst", client_ids=["acme"]), "X-Client-ID": "default"}
    for path in ("/api/ta/watchlist-names", "/api/ta/watchlist"):
        resp = await api_client.get(path, headers=outsider)
        assert resp.status_code == 200
        assert "Lazarus" not in resp.text
