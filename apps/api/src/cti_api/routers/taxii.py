"""Server TAXII 2.1 baca-saja (P7b bagian 5). Auth `require_token`; galat berformat objek TAXII
lewat `errors.py`. Parameter cacat sengaja diparse sendiri dan dijawab 400 (TAXII 2.1), bukan 422
bawaan FastAPI.

Dua koleksi: `indicators` (scope `indicators:read`, P7b) dan `intel` (scope `intel:read`, P7c
spec 5.3: entitas, relasi, report, indikator sebagai satu graf). Discovery/api root menerima token
dengan salah satu scope; daftar koleksi hanya memuat koleksi yang scope-nya dimiliki token, dan
koleksi tanpa scope -> 403."""

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
from cti_api.services.feed import (
    decode_cursor,
    decode_intel_cursor,
    feed_page,
    intel_feed_page,
)
from cti_api.services.stix import indicator_to_stix, stix_ts

TAXII_MEDIA = "application/taxii+json;version=2.1"
STIX_MEDIA = "application/stix+json;version=2.1"
COLLECTION_ID = "6f0e1a52-6a43-4f0b-9b8e-2a7c1d9e4b10"
INTEL_COLLECTION_ID = "c0b7e3d4-2f5a-4e91-8a6d-5b3c9f1e7a20"
DEFAULT_LIMIT = 500
MAX_LIMIT = 1000
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T")


@dataclass
class MatchFilter:
    ids: set[uuid.UUID] | None
    """UUID indikator saja (koleksi `indicators`)."""
    stix_ids: set[str] | None
    """Id STIX utuh yang valid, tipe apa pun (koleksi `intel`)."""
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
    try:
        return ts.astimezone(UTC)
    except OverflowError as exc:  # mis. 0001-01-01T00:00:00+01:00
        raise ValueError("timestamp di luar rentang") from exc


def _csv(value: str) -> set[str]:
    return {v.strip() for v in value.split(",") if v.strip()}


def parse_match(query: Mapping[str, str]) -> MatchFilter:
    ids: set[uuid.UUID] | None = None
    stix_ids: set[str] | None = None
    if (raw := query.get("match[id]")) is not None:
        ids, stix_ids = set(), set()
        for sid in _csv(raw):
            kind, sep, rest = sid.partition("--")
            if not sep:
                raise ValueError(f"id STIX tidak valid: {sid}")
            u = uuid.UUID(rest)  # ValueError bila cacat
            stix_ids.add(f"{kind}--{u}")
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
    return MatchFilter(
        ids=ids, stix_ids=stix_ids, types=types, version=version, spec_versions=specs
    )


def _bad(msg: str) -> HTTPException:
    return HTTPException(400, msg)


async def taxii_accept(request: Request) -> None:
    if not accepts_taxii(request.headers.get("accept")):
        raise HTTPException(406, f"Accept must include {TAXII_MEDIA}")


router = APIRouter(prefix="/taxii2", tags=["taxii"])
_Auth = Depends(require_token("indicators:read", "intel:read"))
_Accept = Depends(taxii_accept)


def _json(body: dict[str, Any], added: list[str] | None = None) -> JSONResponse:
    """`added` = `date_added` (stix_ts) objek di respons, urut feed."""
    headers = {}
    if added:
        headers = {
            "X-TAXII-Date-Added-First": added[0],
            "X-TAXII-Date-Added-Last": added[-1],
        }
    return JSONResponse(body, media_type=TAXII_MEDIA, headers=headers)


# id koleksi -> (scope token, judul, deskripsi); urutan = urutan daftar koleksi
_COLLECTIONS: dict[str, tuple[str, str, str]] = {
    COLLECTION_ID: (
        "indicators:read",
        "Indicators",
        "Threat indicators (STIX 2.1) with TLP-based access",
    ),
    INTEL_COLLECTION_ID: (
        "intel:read",
        "Vareon intel",
        "Threat actors, malware, tools, techniques, vulnerabilities, victims and sectors with "
        "their relationships, reports and indicators (STIX 2.1) with TLP-based access",
    ),
}


def _collection(collection_id: str, principal: MachinePrincipal) -> None:
    if collection_id not in _COLLECTIONS:
        raise HTTPException(404, "Collection not found")
    scope = _COLLECTIONS[collection_id][0]
    if scope not in principal.scopes:
        raise HTTPException(403, f"Token lacks scope: {scope}")


def _collection_body(collection_id: str) -> dict[str, Any]:
    _, title, description = _COLLECTIONS[collection_id]
    return {
        "id": collection_id,
        "title": title,
        "description": description,
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
async def collections(p: MachinePrincipal = _Auth, _a: None = _Accept) -> JSONResponse:
    return _json(
        {
            "collections": [
                _collection_body(cid)
                for cid, (scope, _, _) in _COLLECTIONS.items()
                if scope in p.scopes
            ]
        }
    )


@router.get("/api/collections/{collection_id}/")
async def collection(
    collection_id: str, p: MachinePrincipal = _Auth, _a: None = _Accept
) -> JSONResponse:
    _collection(collection_id, p)
    return _json(_collection_body(collection_id))


@dataclass
class _Listing:
    next_cursor: str | None
    pairs: list[tuple[str, dict[str, Any]]]
    """(date_added, objek STIX), urut feed."""


async def _listing(
    collection_id: str, request: Request, principal: MachinePrincipal, session: AsyncSession
) -> _Listing:
    """Query bersama objects/manifest. Parameter cacat -> 400. `next` menang atas
    `added_after`."""
    q = request.query_params
    intel = collection_id == INTEL_COLLECTION_ID
    after: tuple[datetime, int] | None = None
    intel_after: tuple[datetime, str, int] | None = None
    try:
        raw_limit = q.get("limit")
        limit = DEFAULT_LIMIT if raw_limit is None else min(int(raw_limit), MAX_LIMIT)
        if limit < 1:
            raise ValueError("limit")
        match = parse_match(q)
        added_after = parse_added_after(q.get("added_after"))
        if intel:
            intel_after = decode_intel_cursor(q["next"]) if "next" in q else None
        else:
            after = decode_cursor(q["next"]) if "next" in q else None
    except ValueError as exc:
        raise _bad(f"Malformed parameter: {exc}") from None
    if match.spec_versions is not None and "2.1" not in match.spec_versions:
        return _Listing(None, [])
    pairs: list[tuple[str, dict[str, Any]]]
    if intel:
        ipage = await intel_feed_page(
            session,
            max_tlp=principal.max_tlp,
            limit=limit,
            types=match.types,
            changed_after=None if intel_after else added_after,
            after=intel_after,
            stix_ids=match.stix_ids,
        )
        # `modified` objek intel = stix_ts(feed_changed_at) untuk keempat jenis
        pairs = [(o["modified"], o) for o in ipage.objects]
        next_cursor = ipage.next_cursor
    else:
        if match.types is not None and "indicator" not in match.types:
            return _Listing(None, [])
        page = await feed_page(
            session,
            max_tlp=principal.max_tlp,
            limit=limit,
            changed_after=None if after else added_after,
            after=after,
            stix_ids=match.ids,
        )
        pairs = [
            (stix_ts(i.feed_changed_at), o)
            for i in page.items
            if (o := indicator_to_stix(i)) is not None
        ]
        next_cursor = page.next_cursor
    if isinstance(match.version, datetime):
        # shortcut: disaring setelah query, halaman bisa lebih pendek dari `limit` walau more=true
        want = stix_ts(match.version)
        pairs = [(d, o) for d, o in pairs if o["modified"] == want]
    return _Listing(next_cursor, pairs)


def _envelope(listing: _Listing, key: str, objects: list[Any]) -> dict[str, Any]:
    body: dict[str, Any] = {"more": listing.next_cursor is not None}
    if listing.next_cursor:
        body["next"] = listing.next_cursor
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
    _collection(collection_id, principal)
    listing = await _listing(collection_id, request, principal, session)
    records = [
        {"id": o["id"], "date_added": d, "version": o["modified"], "media_type": STIX_MEDIA}
        for d, o in listing.pairs
    ]
    return _json(_envelope(listing, "objects", records), [d for d, _ in listing.pairs])


@router.get("/api/collections/{collection_id}/objects/")
async def objects(
    collection_id: str,
    request: Request,
    principal: MachinePrincipal = _Auth,
    _a: None = _Accept,
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _collection(collection_id, principal)
    listing = await _listing(collection_id, request, principal, session)
    return _json(
        _envelope(listing, "objects", [o for _, o in listing.pairs]),
        [d for d, _ in listing.pairs],
    )


async def _one(
    collection_id: str, object_id: str, principal: MachinePrincipal, session: AsyncSession
) -> tuple[str, dict[str, Any]]:
    """(date_added, objek) satu objek per id, tanpa settle lag; 404 bila tak terlihat."""
    kind, _, rest = object_id.partition("--")
    try:
        u = uuid.UUID(rest)
    except ValueError:
        raise HTTPException(404, "Object not found") from None
    if collection_id == INTEL_COLLECTION_ID:
        ipage = await intel_feed_page(
            session,
            max_tlp=principal.max_tlp,
            limit=1,
            types=None,
            changed_after=None,
            after=None,
            stix_ids={f"{kind}--{u}"},
        )
        if not ipage.objects:
            raise HTTPException(404, "Object not found")
        return ipage.objects[0]["modified"], ipage.objects[0]
    if kind != "indicator":
        raise HTTPException(404, "Object not found")
    page = await feed_page(session, max_tlp=principal.max_tlp, limit=1, stix_ids={u})
    obj = indicator_to_stix(page.items[0]) if page.items else None
    if obj is None:
        raise HTTPException(404, "Object not found")
    return stix_ts(page.items[0].feed_changed_at), obj


@router.get("/api/collections/{collection_id}/objects/{object_id}/")
async def object_by_id(
    collection_id: str,
    object_id: str,
    principal: MachinePrincipal = _Auth,
    _a: None = _Accept,
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _collection(collection_id, principal)
    added, obj = await _one(collection_id, object_id, principal, session)
    return _json({"more": False, "objects": [obj]}, [added])


@router.get("/api/collections/{collection_id}/objects/{object_id}/versions/")
async def object_versions(
    collection_id: str,
    object_id: str,
    principal: MachinePrincipal = _Auth,
    _a: None = _Accept,
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _collection(collection_id, principal)
    added, obj = await _one(collection_id, object_id, principal, session)
    return _json({"more": False, "versions": [obj["modified"]]}, [added])


@router.post("/api/collections/{collection_id}/objects/")
async def add_objects(
    collection_id: str, p: MachinePrincipal = _Auth, _a: None = _Accept
) -> JSONResponse:
    _collection(collection_id, p)
    raise HTTPException(403, "This collection is read-only")


@router.delete("/api/collections/{collection_id}/objects/{object_id}/")
async def delete_object(
    collection_id: str, object_id: str, p: MachinePrincipal = _Auth, _a: None = _Accept
) -> JSONResponse:
    _collection(collection_id, p)
    raise HTTPException(403, "This collection is read-only")


@router.get("/api/status/{status_id}/")
async def status(status_id: str, _p: MachinePrincipal = _Auth, _a: None = _Accept) -> JSONResponse:
    raise HTTPException(404, "No status resources: the server has no write operations")
