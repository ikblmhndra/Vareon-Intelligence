"""Export CSV `GET /api/sr/entries/export` (redesign 2b, spec 4.4)."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable

import pytest
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.repositories.auth import AsyncRoleRepo
from cti_core.db.repositories.source_reliability import AsyncSourceReliabilityRepo
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_URL = "/api/sr/entries/export"
_COLUMNS = [
    "source_name",
    "admiralty_code",
    "reliability_grade",
    "reliability_label",
    "credibility_code",
    "credibility_label",
    "content_kind",
    "origin",
    "analyst_name",
    "notes",
    "added_date",
    "last_updated",
]


async def _add(
    session: AsyncSession, name: str, grade: str = "B", notes: str = "", analyst: str = "a1"
) -> None:
    entry, _ = await AsyncSourceReliabilityRepo(session).add_entry(
        source_name=name,
        analyst_name=analyst,
        reliability_grade=grade,
        credibility_code="2",
        notes=notes,
    )
    assert entry is not None
    await session.commit()


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


async def test_export_requires_export_data(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    # role uji tanpa `export_data` (role sistem `analyst` membawanya)
    await AsyncRoleRepo(api_session).create(
        name="sr-reader", display_name="SR reader", permissions=["view_intel"], created_by="test"
    )
    await api_session.commit()
    r = await api_client.get(_URL, headers=auth_header(username="alice", role="sr-reader"))
    assert r.status_code == 403


async def test_export_honours_filters(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _add(api_session, "Krebs on Security", grade="A")
    await _add(api_session, "Krebs Mirror", grade="C")
    await _add(api_session, "Other", grade="A")
    await AsyncSourceReliabilityRepo(api_session).ensure_defaults({"Krebs Auto": "news"})
    await api_session.commit()
    r = await api_client.get(
        _URL, params={"search": "krebs", "grade": "A", "origin": "analyst"}, headers=auth_header()
    )
    assert r.status_code == 200
    assert [row["source_name"] for row in _rows(r.text)] == ["Krebs on Security"]
    assert r.headers["content-type"].startswith("text/csv")
    assert "source-reliability-" in r.headers["content-disposition"]


async def test_export_header_row(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _add(api_session, "Src")
    r = await api_client.get(_URL, headers=auth_header())
    assert r.text.lstrip("﻿").splitlines()[0] == ",".join(_COLUMNS)
    row = _rows(r.text)[0]
    assert row["reliability_label"] == "Usually reliable"
    assert row["credibility_label"] == "Probably true"


async def test_export_neutralises_formula_note(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _add(api_session, "Src", notes='=HYPERLINK("http://x")')
    r = await api_client.get(_URL, headers=auth_header())
    assert _rows(r.text)[0]["notes"] == '\'=HYPERLINK("http://x")'


async def test_export_writes_audit(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _add(api_session, "One")
    await _add(api_session, "Two")
    r = await api_client.get(_URL, params={"grade": "B"}, headers=auth_header(username="bob"))
    assert r.status_code == 200
    audit = (
        (
            await api_session.execute(
                select(AuditLogEntry).where(AuditLogEntry.action == "export_source_reliability")
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 1
    assert audit[0].username == "bob"
    assert audit[0].detail["rows"] == 2
    assert audit[0].detail["filters"]["grade"] == "B"


async def test_export_path_not_parsed_as_entry_id(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    """`/entries/export` harus didaftarkan sebelum `/entries/{entry_id}`: kalau tidak, `export`
    diparse sebagai int dan jawabannya 422."""
    r = await api_client.get(_URL, headers=auth_header())
    assert r.status_code == 200
