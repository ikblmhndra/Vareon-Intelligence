"""REST feed `/api/v2/indicators` (P7b): auth, filter state/TLP, paging, CSV, bentuk galat v2."""

from __future__ import annotations

import csv
import datetime
import io
from collections.abc import Callable

import httpx
import pytest
from cti_api import machine_auth
from cti_api.services import feed
from cti_core.db.models.indicator import Indicator, IndicatorTag
from cti_core.db.repositories.auth import AsyncApiTokenRepo
from cti_core.indicator.stix_id import indicator_uuid
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

FIELDS = [
    "id", "stix_id", "type", "value", "state", "valid_from", "valid_until", "first_seen",
    "last_seen", "seen_count", "confidence", "tlp", "pap", "tags", "revoked_at", "changed_at",
]  # fmt: skip


@pytest.fixture(autouse=True)
def _no_lag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feed, "FEED_SETTLE_SECONDS", -5)  # clock_timestamp() > now() in test tx


async def _token(session: AsyncSession, max_tlp: str = "red") -> dict[str, str]:
    token = machine_auth.generate_token()
    await AsyncApiTokenRepo(session).create(
        name="t",
        token_prefix=token[:8],
        token_hash=machine_auth.hash_token(token),
        scopes=["indicators:read"],
        max_tlp=max_tlp,
        created_by="tester",
        expires_at=None,
    )
    return {"Authorization": f"Bearer {token}"}


async def _add(session: AsyncSession, value: str, **kw: object) -> Indicator:
    ind = Indicator(
        type="domain",
        value=value,
        stix_id=indicator_uuid("domain", value),
        **kw,  # type: ignore[arg-type]
    )
    session.add(ind)
    await session.flush()
    return ind


async def test_default_active_only(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
    await _add(api_session, "active.example.com")
    await _add(api_session, "expired.example.com", valid_until=past)
    await _add(api_session, "revoked.example.com", revoked_at=past)
    await _add(api_session, "allow.example.com", auto_suppressed=True)
    resp = await api_client.get("/api/v2/indicators", headers=await _token(api_session))
    assert resp.status_code == 200
    assert [i["value"] for i in resp.json()["items"]] == ["active.example.com"]
    assert resp.json()["next_cursor"] is None


async def test_state_any_includes_revoked(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    await _add(api_session, "a.example.com")
    await _add(api_session, "r.example.com", revoked_at=datetime.datetime.now(datetime.UTC))
    resp = await api_client.get("/api/v2/indicators?state=any", headers=await _token(api_session))
    assert {i["state"] for i in resp.json()["items"]} == {"active", "revoked"}


async def test_cursor_paging(api_client: httpx.AsyncClient, api_session: AsyncSession) -> None:
    for n in range(5):
        await _add(api_session, f"p{n}.example.com")
    headers = await _token(api_session)
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        params = {"limit": "2", **({"cursor": cursor} if cursor else {})}
        body = (await api_client.get("/api/v2/indicators", params=params, headers=headers)).json()
        seen += [i["value"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == [f"p{n}.example.com" for n in range(5)]


async def test_tlp_clear_token_never_sees_amber(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    await _add(api_session, "clear.example.com")
    await _add(api_session, "amber.example.com", tlp="amber")
    headers = await _token(api_session, max_tlp="clear")
    js = await api_client.get("/api/v2/indicators", headers=headers)
    assert [i["value"] for i in js.json()["items"]] == ["clear.example.com"]
    cs = await api_client.get("/api/v2/indicators?format=csv", headers=headers)
    assert "amber.example.com" not in cs.text


async def test_csv_columns_and_next_cursor(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    first = await _add(api_session, "c1.example.com")
    api_session.add_all(
        [
            IndicatorTag(indicator_id=first.id, tag="apt"),
            IndicatorTag(indicator_id=first.id, tag="x"),
        ]
    )
    await api_session.flush()
    await api_session.refresh(first)
    await _add(api_session, "c2.example.com")
    headers = await _token(api_session)
    resp = await api_client.get("/api/v2/indicators?format=csv&limit=1", headers=headers)
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    assert resp.headers["x-next-cursor"]
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == FIELDS
    assert len(rows) == 2 and rows[1][FIELDS.index("tags")] == "apt;x"
    # Accept: text/csv memilih CSV; halaman terakhir tanpa X-Next-Cursor.
    last = await api_client.get(
        "/api/v2/indicators",
        params={"cursor": resp.headers["x-next-cursor"]},
        headers={**headers, "Accept": "text/csv"},
    )
    assert last.headers["content-type"].startswith("text/csv")
    assert "x-next-cursor" not in last.headers


async def test_json_item_fields(api_client: httpx.AsyncClient, api_session: AsyncSession) -> None:
    ind = await _add(api_session, "j.example.com")
    resp = await api_client.get("/api/v2/indicators", headers=await _token(api_session))
    item = resp.json()["items"][0]
    assert list(item) == FIELDS
    assert item["stix_id"] == f"indicator--{indicator_uuid('domain', 'j.example.com')}"
    assert item["id"] == ind.id and item["tags"] == []


@pytest.mark.parametrize(
    "query",
    ["cursor=not-a-cursor", "state=bogus", "changed_after=2026-01-01T00:00:00"],
)
async def test_bad_input_400_v2_shape(
    api_client: httpx.AsyncClient, api_session: AsyncSession, query: str
) -> None:
    resp = await api_client.get(f"/api/v2/indicators?{query}", headers=await _token(api_session))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


async def test_limit_over_max_422_v2_shape(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    resp = await api_client.get("/api/v2/indicators?limit=5001", headers=await _token(api_session))
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["details"] and "input" not in err["details"][0]


async def test_no_token_401_v2_shape(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.get("/api/v2/indicators")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    assert resp.json()["error"]["details"] is None
    assert "WWW-Authenticate" in resp.headers


async def test_jwt_is_not_accepted(
    api_client: httpx.AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    resp = await api_client.get("/api/v2/indicators", headers=auth_header())
    assert resp.status_code == 401


async def test_v1_error_shape_unchanged(
    api_client: httpx.AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    resp = await api_client.get("/api/iocs/ip/203.0.113.250", headers=auth_header())
    assert resp.status_code == 404
    assert set(resp.json()) == {"detail"}


async def test_v2_unknown_path_uses_v2_shape(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.get("/api/v2/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_taxii_unknown_path_uses_taxii_shape(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.get("/taxii2/nope/")
    assert resp.status_code == 404
    assert resp.headers["content-type"] == "application/taxii+json;version=2.1"
    body = resp.json()
    assert body["http_status"] == 404 and body["title"] and "description" in body


async def test_overflow_cursor_and_changed_after_400(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    import base64

    h = await _token(api_session)
    huge = base64.urlsafe_b64encode(b"2026-10-29T00:00:00+00:00|99999999999999999999999").decode()
    for qs in (
        f"cursor={huge}",
        "changed_after=0001-01-01T00:00:00%2B01:00",
        "changed_after=9999-12-31T23:59:59-01:00",
    ):
        resp = await api_client.get(f"/api/v2/indicators?{qs}", headers=h)
        assert resp.status_code == 400, qs
        assert resp.json()["error"]["code"] == "bad_request"
