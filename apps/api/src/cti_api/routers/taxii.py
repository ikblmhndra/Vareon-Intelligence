"""Server TAXII 2.1 baca-saja dengan satu koleksi indikator (P7b bagian 5). Auth `require_token`;
galat berformat objek TAXII lewat `errors.py`. Parameter cacat sengaja diparse sendiri dan
dijawab 400 (TAXII 2.1), bukan 422 bawaan FastAPI."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import get_db
from cti_api.machine_auth import MachinePrincipal, require_token
from cti_api.services.feed import FeedPage, decode_cursor, feed_page
from cti_api.services.stix import indicator_to_stix, stix_ts

TAXII_MEDIA = "application/taxii+json;version=2.1"
STIX_MEDIA = "application/stix+json;version=2.1"
COLLECTION_ID = "6f0e1a52-6a43-4f0b-9b8e-2a7c1d9e4b10"
DEFAULT_LIMIT = 500
MAX_LIMIT = 1000
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T")


@dataclass
class MatchFilter:
    ids: set[uuid.UUID] | None
    types: set[str] | None
    version: Literal["last", "first", "all"] | datetime
    spec_versions: set[str] | None


def accepts_taxii(accept: str | None) -> bool:
    """Benar bila ada media range `application/taxii+json` tanpa `version` atau `version=2.1`.
    `*/*` saja tidak cukup: TAXII mewajibkan media range TAXII."""
    for rng in (accept or "").split(","):
        media, *params = (p.strip() for p in rng.split(";"))
        if media.lower() != "application/taxii+json":
            continue
        versions = [p.partition("=")[2].strip() for p in params if p.lower().startswith("version")]
        if all(v == "2.1" for v in versions):
            return True
    return False


def parse_added_after(value: str | None) -> datetime | None:
    """RFC 3339 dengan zona; `ValueError` untuk selain itu."""
    if value is None:
        return None
    if not _TS.match(value):
        raise ValueError("timestamp tidak valid")
    ts = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    if ts.tzinfo is None:
        raise ValueError("timestamp tanpa zona")
    return ts.astimezone(UTC)


def _csv(value: str) -> set[str]:
    return {v.strip() for v in value.split(",") if v.strip()}


def parse_match(query: Mapping[str, str]) -> MatchFilter:
    ids: set[uuid.UUID] | None = None
    if (raw := query.get("match[id]")) is not None:
        ids = set()
        for sid in _csv(raw):
            kind, sep, rest = sid.partition("--")
            if not sep:
                raise ValueError(f"id STIX tidak valid: {sid}")
            u = uuid.UUID(rest)  # ValueError bila cacat
            if kind == "indicator":  # id tipe lain tidak pernah cocok
                ids.add(u)
    version: Literal["last", "first", "all"] | datetime = "last"
    if (raw := query.get("match[version]")) is not None:
        if raw in ("last", "first", "all"):
            version = raw  # type: ignore[assignment]
        else:
            parsed = parse_added_after(raw)
            assert parsed is not None
            version = parsed
    types = _csv(query["match[type]"]) if "match[type]" in query else None
    specs = _csv(query["match[spec_version]"]) if "match[spec_version]" in query else None
    return MatchFilter(ids=ids, types=types, version=version, spec_versions=specs)


def _bad(msg: str) -> HTTPException:
    return HTTPException(400, msg)


async def taxii_accept(request: Request) -> None:
    if not accepts_taxii(request.headers.get("accept")):
        raise HTTPException(406, f"Accept must include {TAXII_MEDIA}")


router = APIRouter(prefix="/taxii2", tags=["taxii"])
_Auth = Depends(require_token("indicators:read"))
_Accept = Depends(taxii_accept)


def _json(body: dict[str, Any], items: list[Any] | None = None) -> JSONResponse:
    headers = {}
    if items:
        headers = {
            "X-TAXII-Date-Added-First": stix_ts(items[0].feed_changed_at),
            "X-TAXII-Date-Added-Last": stix_ts(items[-1].feed_changed_at),
        }
    return JSONResponse(body, media_type=TAXII_MEDIA, headers=headers)


def _collection(collection_id: str) -> None:
    if collection_id != COLLECTION_ID:
        raise HTTPException(404, "Collection not found")


def _collection_body() -> dict[str, Any]:
    return {
        "id": COLLECTION_ID,
        "title": "Indicators",
        "description": "Threat indicators (STIX 2.1) with TLP-based access",
        "can_read": True,
        "can_write": False,
        "media_types": [STIX_MEDIA],
    }


@router.get("/")
async def discovery(
    request: Request, _p: MachinePrincipal = _Auth, _a: None = _Accept
) -> JSONResponse:
    root = str(request.base_url) + "taxii2/api/"
    return _json({"title": "Vareon Intelligence TAXII", "default": root, "api_roots": [root]})


@router.get("/api/")
async def api_root(_p: MachinePrincipal = _Auth, _a: None = _Accept) -> JSONResponse:
    return _json(
        {
            "title": "Vareon Intelligence",
            "versions": [TAXII_MEDIA],
            "max_content_length": 10485760,
        }
    )


@router.get("/api/collections/")
async def collections(_p: MachinePrincipal = _Auth, _a: None = _Accept) -> JSONResponse:
    return _json({"collections": [_collection_body()]})


@router.get("/api/collections/{collection_id}/")
async def collection(
    collection_id: str, _p: MachinePrincipal = _Auth, _a: None = _Accept
) -> JSONResponse:
    _collection(collection_id)
    return _json(_collection_body())


async def _listing(
    request: Request, principal: MachinePrincipal, session: AsyncSession
) -> tuple[FeedPage, list[tuple[Any, dict[str, Any]]]]:
    """Query bersama objects/manifest. Parameter cacat -> 400."""
    q = request.query_params
    try:
        raw_limit = q.get("limit")
        limit = DEFAULT_LIMIT if raw_limit is None else min(int(raw_limit), MAX_LIMIT)
        if limit < 1:
            raise ValueError("limit")
        match = parse_match(q)
        added_after = parse_added_after(q.get("added_after"))
        after = decode_cursor(q["next"]) if "next" in q else None
    except ValueError as exc:
        raise _bad(f"Malformed parameter: {exc}") from None
    if (match.types is not None and "indicator" not in match.types) or (
        match.spec_versions is not None and "2.1" not in match.spec_versions
    ):
        return FeedPage([], None), []
    page = await feed_page(
        session,
        max_tlp=principal.max_tlp,
        limit=limit,
        changed_after=None if after else added_after,  # `next` menang atas `added_after`
        after=after,
        stix_ids=match.ids,
    )
    pairs = [(i, o) for i in page.items if (o := indicator_to_stix(i)) is not None]
    if isinstance(match.version, datetime):
        # shortcut: disaring setelah query, halaman bisa lebih pendek dari `limit` walau more=true
        want = stix_ts(match.version)
        pairs = [(i, o) for i, o in pairs if o["modified"] == want]
    return page, pairs


def _envelope(page: FeedPage, key: str, objects: list[Any]) -> dict[str, Any]:
    body: dict[str, Any] = {"more": page.next_cursor is not None}
    if page.next_cursor:
        body["next"] = page.next_cursor
    if objects:
        body[key] = objects
    return body


@router.get("/api/collections/{collection_id}/manifest/")
async def manifest(
    collection_id: str,
    request: Request,
    principal: MachinePrincipal = _Auth,
    _a: None = _Accept,
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _collection(collection_id)
    page, pairs = await _listing(request, principal, session)
    records = [
        {
            "id": o["id"],
            "date_added": stix_ts(i.feed_changed_at),
            "version": o["modified"],
            "media_type": STIX_MEDIA,
        }
        for i, o in pairs
    ]
    return _json(_envelope(page, "objects", records), [i for i, _ in pairs])


@router.get("/api/collections/{collection_id}/objects/")
async def objects(
    collection_id: str,
    request: Request,
    principal: MachinePrincipal = _Auth,
    _a: None = _Accept,
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _collection(collection_id)
    page, pairs = await _listing(request, principal, session)
    return _json(_envelope(page, "objects", [o for _, o in pairs]), [i for i, _ in pairs])


async def _one(
    object_id: str, principal: MachinePrincipal, session: AsyncSession
) -> tuple[Any, dict[str, Any]]:
    kind, _, rest = object_id.partition("--")
    try:
        u = uuid.UUID(rest)
    except ValueError:
        u = None
    if kind != "indicator" or u is None:
        raise HTTPException(404, "Object not found")
    page = await feed_page(session, max_tlp=principal.max_tlp, limit=1, stix_ids={u})
    obj = indicator_to_stix(page.items[0]) if page.items else None
    if obj is None:
        raise HTTPException(404, "Object not found")
    return page.items[0], obj


@router.get("/api/collections/{collection_id}/objects/{object_id}/")
async def object_by_id(
    collection_id: str,
    object_id: str,
    principal: MachinePrincipal = _Auth,
    _a: None = _Accept,
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _collection(collection_id)
    ind, obj = await _one(object_id, principal, session)
    return _json({"more": False, "objects": [obj]}, [ind])


@router.get("/api/collections/{collection_id}/objects/{object_id}/versions/")
async def object_versions(
    collection_id: str,
    object_id: str,
    principal: MachinePrincipal = _Auth,
    _a: None = _Accept,
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _collection(collection_id)
    ind, obj = await _one(object_id, principal, session)
    return _json({"more": False, "versions": [obj["modified"]]}, [ind])


@router.post("/api/collections/{collection_id}/objects/")
async def add_objects(
    collection_id: str, _p: MachinePrincipal = _Auth, _a: None = _Accept
) -> JSONResponse:
    _collection(collection_id)
    raise HTTPException(403, "This collection is read-only")


@router.delete("/api/collections/{collection_id}/objects/{object_id}/")
async def delete_object(
    collection_id: str, object_id: str, _p: MachinePrincipal = _Auth, _a: None = _Accept
) -> JSONResponse:
    _collection(collection_id)
    raise HTTPException(403, "This collection is read-only")


@router.get("/api/status/{status_id}/")
async def status(status_id: str, _p: MachinePrincipal = _Auth, _a: None = _Accept) -> JSONResponse:
    raise HTTPException(404, "No status resources: the server has no write operations")
