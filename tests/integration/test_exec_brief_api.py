"""Pembuatan brief bersama (`draft_brief`) dan endpoint `/api/exec/brief*`: tanpa bagian
analyst/klien, error LLM jadi `BriefGenerationError` / 502, satu brief untuk semua klien.
LLM selalu di-stub."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from cti_api.services import exec_brief as eb
from cti_api.services import exec_dashboard
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.exec_brief import AsyncExecBriefRepo
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _boom(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("bagian analyst/klien tidak boleh dihitung untuk brief")


async def test_brief_skips_analyst_and_client_sections(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "_get_recent_clusters",
        "_get_pending_fp_queue",
        "_get_critical_cves",
        "_get_source_reliability_spread",
    ):
        monkeypatch.setattr(exec_dashboard, name, _boom)
    monkeypatch.setattr(eb, "_call_llm", lambda _m: ("# Brief", "model-x"))
    draft = await eb.draft_brief(async_db_session, filters=eb.DEFAULT_FILTERS)
    assert (draft.markdown, draft.model) == ("# Brief", "model-x")
    assert draft.prompt_version == eb._PROMPT_VERSION


async def test_draft_empty_answer_raises(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(eb, "_call_llm", lambda _m: ("  \n", "m"))
    with pytest.raises(eb.BriefGenerationError) as ei:
        await eb.draft_brief(async_db_session, filters=eb.DEFAULT_FILTERS)
    assert ei.value.error_type == "empty"


async def test_draft_llm_error_raises_generation_error(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(_m: str) -> tuple[str, str]:
        raise TimeoutError

    monkeypatch.setattr(eb, "_call_llm", _fail)
    with pytest.raises(eb.BriefGenerationError) as ei:
        await eb.draft_brief(async_db_session, filters=eb.DEFAULT_FILTERS)
    assert ei.value.error_type == "TimeoutError"


# --- endpoint ---------------------------------------------------------------------------------

_F = {"days": 90, "incident_only": True, "confirmed_only": False}


async def _seed(
    session: AsyncSession, offset: int = 0, md: str = "# Brief", by: str = "scheduler", **f: Any
) -> datetime.date:
    d = eb.brief_today() + datetime.timedelta(days=offset)
    await AsyncExecBriefRepo(session).upsert(
        brief_date=d,
        markdown=md,
        filters={**_F, **f},
        generated_by=by,
        model="m0",
        prompt_version="pv",
        replace=True,
    )
    await session.commit()
    return d


async def test_get_today(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Any
) -> None:
    d = await _seed(api_session, md="# Hari ini")
    body = (await api_client.get("/api/exec/brief", headers=auth_header())).json()
    assert body["today"] == d.isoformat()
    assert body["brief"]["brief_date"] == d.isoformat()
    assert body["brief"]["markdown"] == "# Hari ini"
    assert body["brief"]["is_default_filters"] is True
    assert body["brief"]["filters"] == _F


async def test_get_falls_back_to_latest_within_30_days(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Any
) -> None:
    d = await _seed(api_session, -3, "# Tiga hari lalu")
    await _seed(api_session, -10, "# Lebih lama")
    body = (await api_client.get("/api/exec/brief", headers=auth_header())).json()
    assert body["brief"]["brief_date"] == d.isoformat()


async def test_get_null_when_none(api_client: AsyncClient, auth_header: Any) -> None:
    body = (await api_client.get("/api/exec/brief", headers=auth_header())).json()
    assert body["brief"] is None and body["today"]


async def test_get_explicit_date(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Any
) -> None:
    await _seed(api_session, 0, "# Hari ini")
    old = await _seed(api_session, -2, "# Dua hari lalu")
    got = (
        await api_client.get(f"/api/exec/brief?date={old.isoformat()}", headers=auth_header())
    ).json()
    assert got["brief"]["markdown"] == "# Dua hari lalu"
    none = (await api_client.get("/api/exec/brief?date=2001-01-01", headers=auth_header())).json()
    assert none["brief"] is None


async def test_two_clients_read_identical_brief(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Any
) -> None:
    repo = AsyncClientRepo(api_session)
    await repo.ensure_default()
    await repo.create(client_id="other", name="Other", countries=[])
    await _seed(api_session)
    await _seed(api_session, -1)
    h = auth_header(client_ids=["default", "other"])
    for path in ("/api/exec/brief", "/api/exec/brief/dates"):
        a = await api_client.get(path, headers={**h, "X-Client-ID": "default"})
        b = await api_client.get(path, headers={**h, "X-Client-ID": "other"})
        assert a.status_code == b.status_code == 200
        assert a.json() == b.json()


async def test_today_matches_brief_today(api_client: AsyncClient, auth_header: Any) -> None:
    for path in ("/api/exec/brief", "/api/exec/brief/dates"):
        body = (await api_client.get(path, headers=auth_header())).json()
        assert body["today"] == eb.brief_today().isoformat()


async def test_dates_order_and_window(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Any
) -> None:
    kept = [await _seed(api_session, o) for o in (0, -30, -5)]
    await _seed(api_session, -31)
    body = (await api_client.get("/api/exec/brief/dates", headers=auth_header())).json()
    assert body["dates"] == [d.isoformat() for d in sorted(kept, reverse=True)]


async def test_post_replaces_scheduler_row_and_sets_generated_by(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed(api_session, md="# Scheduler")
    monkeypatch.setattr(eb, "_call_llm", lambda _m: ("# Manual", "model-y"))
    r = await api_client.post("/api/exec/brief", headers=auth_header(username="alice"))
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["markdown"], out["generated_by"], out["model"]) == ("# Manual", "alice", "model-y")
    assert out["brief_date"] == eb.brief_today().isoformat()
    assert out["is_default_filters"] is True
    got = (await api_client.get("/api/exec/brief", headers=auth_header())).json()
    assert got["brief"]["markdown"] == "# Manual"


async def test_post_non_default_filters_flagged(
    api_client: AsyncClient, auth_header: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(eb, "_call_llm", lambda _m: ("# M", "m"))
    r = await api_client.post(
        "/api/exec/brief?days=30&incident_only=false&confirmed_only=true", headers=auth_header()
    )
    out = r.json()
    assert out["is_default_filters"] is False
    assert out["filters"] == {"days": 30, "incident_only": False, "confirmed_only": True}


@pytest.mark.parametrize("days", [6, 366])
async def test_post_days_bounds(
    api_client: AsyncClient, auth_header: Any, monkeypatch: pytest.MonkeyPatch, days: int
) -> None:
    monkeypatch.setattr(eb, "_call_llm", lambda _m: ("# M", "m"))
    r = await api_client.post(f"/api/exec/brief?days={days}", headers=auth_header())
    assert r.status_code == 422


async def test_post_llm_failure_502_keeps_row(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = await _seed(api_session, md="# Tetap")

    def _fail(_m: str) -> tuple[str, str]:
        raise TimeoutError

    monkeypatch.setattr(eb, "_call_llm", _fail)
    r = await api_client.post("/api/exec/brief", headers=auth_header())
    assert r.status_code == 502
    assert r.json() == {"detail": "Brief generation failed. Try again later."}
    row = await AsyncExecBriefRepo(api_session).get(d)
    assert row is not None and row.markdown == "# Tetap" and row.generated_by == "scheduler"
    audit = await api_session.scalars(
        select(AuditLogEntry).where(AuditLogEntry.action == "generate_exec_brief")
    )
    assert audit.first() is None


async def test_post_writes_audit(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eb, "_call_llm", lambda _m: ("# M", "m"))
    await api_client.post("/api/exec/brief?days=14", headers=auth_header(username="alice"))
    row = (
        await api_session.scalars(
            select(AuditLogEntry).where(AuditLogEntry.action == "generate_exec_brief")
        )
    ).one()
    assert row.username == "alice"
    assert row.detail == {
        "days": 14,
        "incident_only": True,
        "confirmed_only": False,
        "brief_date": eb.brief_today().isoformat(),
    }
    assert row.ip_address


async def test_post_ignores_x_client_id(
    api_client: AsyncClient, auth_header: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brief platform-wide: header klien yang tidak dikenal tidak boleh membuat 403/404."""
    monkeypatch.setattr(eb, "_call_llm", lambda _m: ("# M", "m"))
    r = await api_client.post(
        "/api/exec/brief", headers={**auth_header(), "X-Client-ID": "tidak-ada"}
    )
    assert r.status_code == 200, r.text
