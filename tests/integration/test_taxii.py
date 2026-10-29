"""Server TAXII 2.1 `/taxii2/` (P7b task 6): protokol, paging, TLP, revoked, galat."""

from __future__ import annotations

import base64
import datetime

import httpx
import pytest
from cti_api import machine_auth
from cti_api.routers.taxii import COLLECTION_ID, STIX_MEDIA, TAXII_MEDIA
from cti_api.services import feed
from cti_api.services.stix import stix_ts
from cti_core.db.models.indicator import Indicator
from cti_core.db.repositories.auth import AsyncApiTokenRepo
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from cti_core.indicator.stix_id import indicator_uuid
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

COL = f"/taxii2/api/collections/{COLLECTION_ID}"


@pytest.fixture(autouse=True)
def _no_lag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feed, "FEED_SETTLE_SECONDS", 0)


async def _hdr(session: AsyncSession, max_tlp: str = "red", basic: bool = False) -> dict[str, str]:
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
    auth = (
        "Basic " + base64.b64encode(f"u:{token}".encode()).decode() if basic else f"Bearer {token}"
    )
    return {"Authorization": auth, "Accept": TAXII_MEDIA}


async def _add(session: AsyncSession, value: str, **kw: object) -> Indicator:
    ind = Indicator(
        type="domain",
        value=value,
        stix_id=indicator_uuid("domain", value),
        **kw,  # type: ignore[arg-type]
    )
    session.add(ind)
    await session.flush()
    await session.refresh(ind)
    return ind


def _sid(value: str) -> str:
    return f"indicator--{indicator_uuid('domain', value)}"


async def _seed(session: AsyncSession, n: int = 5) -> list[Indicator]:
    # feed_changed_at eksplisit dan berbeda: now() konstan di dalam transaksi test
    base = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    return [
        await _add(
            session,
            f"d{i}.example.com",
            feed_changed_at=base + datetime.timedelta(seconds=i),
        )
        for i in range(n)
    ]


def _ct(resp: httpx.Response) -> str:
    return resp.headers["content-type"]


@pytest.mark.parametrize("basic", [False, True])
async def test_discovery_root_collections(
    api_client: httpx.AsyncClient, api_session: AsyncSession, basic: bool
) -> None:
    h = await _hdr(api_session, basic=basic)
    r = await api_client.get("/taxii2/", headers=h)
    assert r.status_code == 200 and _ct(r) == TAXII_MEDIA
    assert r.json()["api_roots"] == ["http://test/taxii2/api/"]
    assert r.json()["default"] == "http://test/taxii2/api/"
    r = await api_client.get("/taxii2/api/", headers=h)
    assert _ct(r) == TAXII_MEDIA
    assert r.json()["versions"] == [TAXII_MEDIA]
    assert r.json()["max_content_length"] == 10485760
    r = await api_client.get("/taxii2/api/collections/", headers=h)
    assert _ct(r) == TAXII_MEDIA
    assert [c["id"] for c in r.json()["collections"]] == [COLLECTION_ID]
    r = await api_client.get(COL + "/", headers=h)
    body = r.json()
    assert _ct(r) == TAXII_MEDIA
    assert body["id"] == COLLECTION_ID
    assert body["can_read"] is True and body["can_write"] is False
    assert body["media_types"] == [STIX_MEDIA]


async def test_406_without_taxii_accept(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    h = await _hdr(api_session)
    for accept in ("application/json", "*/*", "application/taxii+json;version=2.0"):
        r = await api_client.get("/taxii2/", headers={**h, "Accept": accept})
        assert r.status_code == 406
        assert _ct(r) == TAXII_MEDIA
        assert r.json()["http_status"] == 406


async def test_objects_paging_and_headers(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    rows = await _seed(api_session, 5)
    h = await _hdr(api_session)
    seen: list[str] = []
    r = await api_client.get(COL + "/objects/?limit=2", headers=h)
    assert r.status_code == 200 and _ct(r) == TAXII_MEDIA
    body = r.json()
    assert body["more"] is True and body["next"]
    assert len(body["objects"]) == 2
    assert r.headers["X-TAXII-Date-Added-First"] == stix_ts(rows[0].feed_changed_at)
    assert r.headers["X-TAXII-Date-Added-Last"] == stix_ts(rows[1].feed_changed_at)
    seen += [o["id"] for o in body["objects"]]
    while body["more"]:
        r = await api_client.get(
            COL + "/objects/", params={"limit": 2, "next": body["next"]}, headers=h
        )
        body = r.json()
        seen += [o["id"] for o in body["objects"]]
    assert body["more"] is False and "next" not in body
    assert sorted(seen) == sorted(_sid(f"d{i}.example.com") for i in range(5))


async def test_empty_has_no_date_headers(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    r = await api_client.get(COL + "/objects/", headers=await _hdr(api_session))
    assert r.status_code == 200
    assert r.json() == {"more": False}
    assert "X-TAXII-Date-Added-First" not in r.headers


async def test_added_after_strict(api_client: httpx.AsyncClient, api_session: AsyncSession) -> None:
    rows = await _seed(api_session, 2)
    h = await _hdr(api_session)
    ts = rows[0].feed_changed_at.astimezone(datetime.UTC).isoformat()
    r = await api_client.get(COL + "/objects/", params={"added_after": ts}, headers=h)
    ids = [o["id"] for o in r.json().get("objects", [])]
    assert ids == [_sid(rows[1].value)]
    ts_last = rows[-1].feed_changed_at.astimezone(datetime.UTC).isoformat()
    r = await api_client.get(COL + "/objects/", params={"added_after": ts_last}, headers=h)
    assert "objects" not in r.json()


async def test_manifest_records(api_client: httpx.AsyncClient, api_session: AsyncSession) -> None:
    rows = await _seed(api_session, 1)
    r = await api_client.get(COL + "/manifest/", headers=await _hdr(api_session))
    assert r.status_code == 200 and _ct(r) == TAXII_MEDIA
    rec = r.json()["objects"][0]
    assert rec == {
        "id": _sid(rows[0].value),
        "date_added": stix_ts(rows[0].feed_changed_at),
        "version": stix_ts(rows[0].feed_changed_at),
        "media_type": STIX_MEDIA,
    }
    assert r.headers["X-TAXII-Date-Added-First"] == rec["date_added"]


async def test_object_by_id_and_versions(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    rows = await _seed(api_session, 2)
    h = await _hdr(api_session)
    sid = _sid(rows[0].value)
    r = await api_client.get(f"{COL}/objects/{sid}/", headers=h)
    assert r.status_code == 200 and _ct(r) == TAXII_MEDIA
    assert [o["id"] for o in r.json()["objects"]] == [sid]
    assert "X-TAXII-Date-Added-First" in r.headers
    r = await api_client.get(f"{COL}/objects/{sid}/versions/", headers=h)
    assert r.json() == {"more": False, "versions": [stix_ts(rows[0].feed_changed_at)]}
    r = await api_client.get(f"{COL}/objects/{_sid('nope.example.com')}/", headers=h)
    assert r.status_code == 404
    r = await api_client.get(f"{COL}/objects/malware--not-a-uuid/", headers=h)
    assert r.status_code == 404


async def test_object_above_tlp_404(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    amber = await _add(api_session, "amber.example.com", tlp="amber")
    await _add(api_session, "clear.example.com", tlp="clear")
    h = await _hdr(api_session, max_tlp="clear")
    sid = _sid(amber.value)
    r = await api_client.get(COL + "/objects/", headers=h)
    assert [o["id"] for o in r.json()["objects"]] == [_sid("clear.example.com")]
    r = await api_client.get(COL + "/manifest/", headers=h)
    assert [o["id"] for o in r.json()["objects"]] == [_sid("clear.example.com")]
    assert (await api_client.get(f"{COL}/objects/{sid}/", headers=h)).status_code == 404
    assert (await api_client.get(f"{COL}/objects/{sid}/versions/", headers=h)).status_code == 404


async def test_revoked_published(api_client: httpx.AsyncClient, api_session: AsyncSession) -> None:
    ind = await _add(api_session, "fp.example.com")
    await AsyncIndicatorRepo(api_session).add_feedback(ind, verdict="fp", submitted_by="tester")
    r = await api_client.get(COL + "/objects/", headers=await _hdr(api_session))
    obj = r.json()["objects"][0]
    assert obj["id"] == _sid("fp.example.com") and obj["revoked"] is True


async def test_match_filters(api_client: httpx.AsyncClient, api_session: AsyncSession) -> None:
    rows = await _seed(api_session, 3)
    h = await _hdr(api_session)
    r = await api_client.get(COL + "/objects/?match[type]=malware", headers=h)
    assert r.json() == {"more": False}
    r = await api_client.get(COL + "/objects/?match[spec_version]=2.0", headers=h)
    assert r.json() == {"more": False}
    r = await api_client.get(COL + "/objects/?match[type]=indicator,malware", headers=h)
    assert len(r.json()["objects"]) == 3
    wanted = f"{_sid(rows[0].value)},{_sid(rows[2].value)}"
    r = await api_client.get(COL + "/objects/", params={"match[id]": wanted}, headers=h)
    assert sorted(o["id"] for o in r.json()["objects"]) == sorted(wanted.split(","))
    r = await api_client.get(
        COL + "/objects/",
        params={"match[version]": stix_ts(rows[1].feed_changed_at)},
        headers=h,
    )
    assert [o["id"] for o in r.json()["objects"]] == [_sid(rows[1].value)]
    r = await api_client.get(COL + "/objects/?match[foo]=bar", headers=h)
    assert len(r.json()["objects"]) == 3


async def test_limit_clamped_and_validated(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    h = await _hdr(api_session)
    assert (await api_client.get(COL + "/objects/?limit=99999", headers=h)).status_code == 200
    for bad in ("0", "-1", "abc"):
        assert (await api_client.get(COL + f"/objects/?limit={bad}", headers=h)).status_code == 400


async def test_bad_next_400_taxii_error(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    h = await _hdr(api_session)
    for qs in ("next=garbage", "added_after=yesterday", "match[id]=indicator--bad"):
        r = await api_client.get(COL + f"/objects/?{qs}", headers=h)
        assert r.status_code == 400, qs
        assert _ct(r) == TAXII_MEDIA
        assert r.json()["http_status"] == 400 and r.json()["title"]


async def test_write_and_status_and_unknown(
    api_client: httpx.AsyncClient, api_session: AsyncSession
) -> None:
    h = await _hdr(api_session)
    r = await api_client.post(COL + "/objects/", headers=h, json={})
    assert r.status_code == 403 and _ct(r) == TAXII_MEDIA
    r = await api_client.delete(f"{COL}/objects/{_sid('x.example.com')}/", headers=h)
    assert r.status_code == 403
    r = await api_client.get("/taxii2/api/status/abc/", headers=h)
    assert r.status_code == 404 and _ct(r) == TAXII_MEDIA
    for path in (
        "/taxii2/api/collections/00000000-0000-4000-8000-000000000000/",
        "/taxii2/api/collections/00000000-0000-4000-8000-000000000000/objects/",
    ):
        assert (await api_client.get(path, headers=h)).status_code == 404


async def test_no_token_401_www_authenticate(api_client: httpx.AsyncClient) -> None:
    r = await api_client.get("/taxii2/", headers={"Accept": TAXII_MEDIA})
    assert r.status_code == 401
    assert "Basic" in r.headers["www-authenticate"]
    assert _ct(r) == TAXII_MEDIA
