"""Blok `cve_ingest` di `GET /api/data-health`: status dari umur poll mirror dan rekonsiliasi."""

from __future__ import annotations

import datetime

import pytest
from cti_core.config import get_settings
from cti_core.cve_mirror_sync import RECONCILE_KEY, STATE_KEY
from cti_core.db.models.report_state import JobState
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


def _ago(**kw: float) -> str:
    return (datetime.datetime.now(datetime.UTC) - datetime.timedelta(**kw)).isoformat()


async def _seed(
    s: AsyncSession, *, polled: str | None, pending: int = 0, reconcile: dict | None = None
) -> None:
    await s.execute(delete(JobState).where(JobState.key.in_([STATE_KEY, RECONCILE_KEY])))
    if polled is not None:
        items = [{"cve_id": f"CVE-2026-{1000 + i}", "link": "l"} for i in range(pending)]
        s.add(JobState(key=STATE_KEY, value={"polled_at": polled, "pending": items}))
    if reconcile is not None:
        s.add(JobState(key=RECONCILE_KEY, value=reconcile))
    await s.flush()


async def _get(api_client: AsyncClient, auth_header) -> dict:
    resp = await api_client.get("/api/data-health", headers=auth_header(role="analyst"))
    assert resp.status_code == 200
    return resp.json()["cve_ingest"]


@pytest.fixture
def mirror_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CVE_MIRROR__ENABLED", "true")
    monkeypatch.setenv("CVE_MIRROR__PROMOTE", "live")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


async def test_cve_ingest_off_when_mirror_disabled(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    await _seed(api_session, polled=_ago(minutes=1))
    ci = await _get(api_client, auth_header)
    assert ci["enabled"] is False
    assert ci["status"] == "off"


async def test_cve_ingest_red_when_sync_stale(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, mirror_on
) -> None:
    await _seed(api_session, polled=_ago(minutes=16), reconcile={"ran_at": _ago(minutes=5)})
    ci = await _get(api_client, auth_header)
    assert ci["enabled"] is True
    assert ci["promote"] == "live"
    assert ci["status"] == "red"


async def test_cve_ingest_amber_without_reconcile(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, mirror_on
) -> None:
    await _seed(api_session, polled=_ago(minutes=2))
    ci = await _get(api_client, auth_header)
    assert ci["status"] == "amber"
    assert ci["last_reconcile"] is None


async def test_cve_ingest_ok_reports_counts(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, mirror_on
) -> None:
    await _seed(
        api_session,
        polled=_ago(minutes=2),
        pending=2,
        reconcile={
            "ran_at": _ago(minutes=30),
            "last_report": {"status": "ok", "fixed": 3, "planned": 3},
        },
    )
    ci = await _get(api_client, auth_header)
    assert ci["status"] == "ok"
    assert ci["pending"] == 2
    assert ci["last_reconcile"]["fixed"] == 3
    assert ci["last_sync_at"] is not None
    assert ci["last_reconcile_at"] is not None
