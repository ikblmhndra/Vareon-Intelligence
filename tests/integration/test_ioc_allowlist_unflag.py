"""Router `iocs.py` (rilis 0.8.6, review akhir): menghapus entri allowlist membatalkan tandanya
(hanya alasan persis entri itu), dan lookup/pencarian IOC memakai nilai kanonik supaya nilai
yang di-paste dalam bentuk defanged (`evil[.]com`) tetap ketemu -- Postgres REAL."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_REASON = "allowlist:url_domain:unflag.example (infrastructure-abuse)"
_OTHER = "allowlist:url_domain:other.example (infrastructure-abuse)"


async def test_removing_allowlist_entry_unflags_its_iocs(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    add = await api_client.post(
        "/api/iocs/allowlist",
        headers=auth_header(role="admin"),
        json={"type": "url_domain", "value": "unflag.example"},
    )
    entry_id = add.json()["id"]
    repo = AsyncIndicatorRepo(api_session)
    flagged = await repo.upsert(
        type="domain",
        value="cdn.unflag.example",
        source_url="https://a.example/1",
        source_name="A",
        suppression_reason=_REASON,
    )
    other = await repo.upsert(
        type="domain",
        value="x.other.example",
        source_url="https://a.example/1",
        source_name="A",
        suppression_reason=_OTHER,
    )
    flagged_id, other_id = flagged.id, other.id
    assert flagged.auto_suppressed is True

    resp = await api_client.delete(
        f"/api/iocs/allowlist/{entry_id}", headers=auth_header(role="admin")
    )
    assert resp.status_code == 200

    api_session.expire_all()
    unflagged = await repo.get_by_id(flagged_id)
    untouched = await repo.get_by_id(other_id)
    assert unflagged is not None and untouched is not None
    assert (unflagged.auto_suppressed, unflagged.suppression_reason) == (False, None)
    assert (untouched.auto_suppressed, untouched.suppression_reason) == (True, _OTHER)


async def test_lookup_and_search_accept_defanged_values(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await AsyncIndicatorRepo(api_session).upsert(
        type="domain", value="lookup-evil.com", source_url="https://a.example/2", source_name="A"
    )

    detail = await api_client.get("/api/iocs/domain/Lookup-Evil[.]COM", headers=auth_header())
    assert detail.status_code == 200
    assert detail.json()["value"] == "lookup-evil.com"

    listed = await api_client.get(
        "/api/iocs", params={"search": "lookup-evil[.]com"}, headers=auth_header()
    )
    assert [i["value"] for i in listed.json()["iocs"]] == ["lookup-evil.com"]

    tagged = await api_client.post(
        "/api/iocs/domain/lookup-evil[.]com/tags",
        headers=auth_header(role="admin"),
        json={"tags": ["t1"]},
    )
    assert tagged.status_code == 200
