"""Export CSV `GET /api/iocs/export` (redesign 2b, spec 4.5)."""

from __future__ import annotations

import csv
import datetime
import io
from collections.abc import Callable

import pytest
from cti_api.routers import iocs as iocs_router
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.indicator import Indicator, IndicatorTag
from cti_core.db.repositories import indicator as indicator_repo
from cti_core.db.repositories.auth import AsyncRoleRepo
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_URL = "/api/iocs/export"
_COLUMNS = [
    "id",
    "type",
    "value",
    "state",
    "tlp",
    "pap",
    "confidence_score",
    "actionability_score",
    "actionability_label",
    "recommended_action",
    "seen_count",
    "first_seen",
    "last_seen",
    "tp_count",
    "fp_count",
    "threat_actors",
    "tags",
    "auto_suppressed",
    "suppression_reason",
    "revoked_at",
]


async def _ioc(session: AsyncSession, value: str, type: str = "ip") -> Indicator:
    ind = await AsyncIndicatorRepo(session).upsert(
        type=type, value=value, source_url="https://a.example/r", source_name="A"
    )
    await session.commit()
    return ind


def _rows(text_: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text_.lstrip("﻿"))))


def _values(text_: str) -> list[str]:
    return [r["value"] for r in _rows(text_)]


async def test_filter_ioc_type(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _ioc(api_session, "1.1.1.1")
    await _ioc(api_session, "evil.example", "domain")
    r = await api_client.get(_URL, params={"ioc_type": "domain"}, headers=auth_header())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "iocs-" in r.headers["content-disposition"]
    assert r.text.lstrip("﻿").splitlines()[0] == ",".join(_COLUMNS)
    assert _values(r.text) == ["evil.example"]


async def test_filter_search(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _ioc(api_session, "evil.example", "domain")
    await _ioc(api_session, "good.example", "domain")
    # nilai tersimpan kanonik: `evil[.]example` yang di-paste tetap ketemu
    r = await api_client.get(
        _URL, params={"ioc_type": "domain", "search": "evil[.]example"}, headers=auth_header()
    )
    assert _values(r.text) == ["evil.example"]


async def test_filter_actionability(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    a = await _ioc(api_session, "1.1.1.1")
    await _ioc(api_session, "2.2.2.2")
    await api_session.execute(
        update(Indicator).where(Indicator.id == a.id).values(actionability_label="act_now")
    )
    await api_session.commit()
    r = await api_client.get(_URL, params={"actionability": "act_now"}, headers=auth_header())
    assert _values(r.text) == ["1.1.1.1"]


async def test_filter_state(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _ioc(api_session, "1.1.1.1")
    b = await _ioc(api_session, "2.2.2.2")
    await api_session.execute(
        update(Indicator)
        .where(Indicator.id == b.id)
        .values(revoked_at=datetime.datetime.now(datetime.UTC))
    )
    await api_session.commit()
    r = await api_client.get(_URL, params={"state": "revoked"}, headers=auth_header())
    assert _values(r.text) == ["2.2.2.2"]
    assert _rows(r.text)[0]["state"] == "revoked"


async def test_suppressed_excluded_by_default(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _ioc(api_session, "1.1.1.1")
    s = await _ioc(api_session, "2.2.2.2")
    await api_session.execute(
        update(Indicator).where(Indicator.id == s.id).values(auto_suppressed=True)
    )
    await api_session.commit()
    r = await api_client.get(_URL, headers=auth_header())
    assert _values(r.text) == ["1.1.1.1"]
    r2 = await api_client.get(_URL, params={"include_suppressed": "true"}, headers=auth_header())
    assert sorted(_values(r2.text)) == ["1.1.1.1", "2.2.2.2"]


async def test_state_allowlisted_includes_hidden_rows(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _ioc(api_session, "1.1.1.1")
    s = await _ioc(api_session, "2.2.2.2")
    await api_session.execute(
        update(Indicator).where(Indicator.id == s.id).values(auto_suppressed=True)
    )
    await api_session.commit()
    r = await api_client.get(_URL, params={"state": "allowlisted"}, headers=auth_header())
    assert _values(r.text) == ["2.2.2.2"]


async def test_cap_sets_truncated_header(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for i in range(4):
        await _ioc(api_session, f"10.0.0.{i}")
    monkeypatch.setattr(iocs_router, "_EXPORT_CAP", 3)
    r = await api_client.get(_URL, headers=auth_header())
    assert len(_rows(r.text)) == 3
    assert r.headers["x-export-truncated"] == "true"
    monkeypatch.setattr(iocs_router, "_EXPORT_CAP", 4)
    r2 = await api_client.get(_URL, headers=auth_header())
    assert len(_rows(r2.text)) == 4
    assert "x-export-truncated" not in r2.headers


async def test_export_requires_export_data(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    # role uji tanpa `export_data` (role sistem `analyst` membawanya)
    await AsyncRoleRepo(api_session).create(
        name="ioc-reader", display_name="IOC reader", permissions=["view_ioc"], created_by="test"
    )
    await api_session.commit()
    r = await api_client.get(_URL, headers=auth_header(username="alice", role="ioc-reader"))
    assert r.status_code == 403


async def test_value_starting_with_at_is_neutralised(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _ioc(api_session, "@x", "email")
    r = await api_client.get(_URL, headers=auth_header())
    assert _values(r.text) == ["'@x"]


async def test_export_writes_audit(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _ioc(api_session, "1.1.1.1")
    await _ioc(api_session, "evil.example", "domain")
    r = await api_client.get(_URL, params={"ioc_type": "ip"}, headers=auth_header(username="bob"))
    assert r.status_code == 200
    audit = (
        (
            await api_session.execute(
                select(AuditLogEntry).where(AuditLogEntry.action == "export_iocs")
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 1
    assert audit[0].username == "bob"
    assert audit[0].detail["rows"] == 1
    assert audit[0].detail["filters"]["ioc_type"] == "ip"


async def test_export_batches_ties_complete(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch keyset berukuran 2 dan lima baris dengan `last_seen_at` sama: baris yang kembar di
    kunci sort melewati batas batch tidak boleh terduplikasi atau terlewat."""
    for i in range(5):
        await _ioc(api_session, f"10.0.0.{i}")
    await api_session.execute(text("UPDATE indicators SET last_seen_at = '2026-01-01T00:00:00+00'"))
    await api_session.commit()
    monkeypatch.setattr(indicator_repo, "_EXPORT_BATCH", 2)
    r = await api_client.get(_URL, headers=auth_header())
    ids = [int(row["id"]) for row in _rows(r.text)]
    assert len(ids) == 5
    assert len(set(ids)) == 5
    assert ids == sorted(ids, reverse=True)


async def test_iter_export_skips_sources_and_feedback(api_session: AsyncSession) -> None:
    """Export tidak membaca `sources`/`feedback`: keduanya di-`noload` supaya puluhan ribu baris
    tidak menarik semua riwayat sumber ke memori. `tags` dan `mentions` tetap dimuat (CSV butuh)."""
    await _ioc(api_session, "1.1.1.1")
    ind_id = (await api_session.execute(select(Indicator.id))).scalar_one()
    api_session.add(IndicatorTag(indicator_id=ind_id, tag="c2"))
    await api_session.commit()
    api_session.expunge_all()
    batches = [b async for b in AsyncIndicatorRepo(api_session).iter_export(sort_by=None, limit=10)]
    row = batches[0][0]
    assert row.sources == []
    assert row.feedback == []
    assert [t.tag for t in row.tags] == ["c2"]
