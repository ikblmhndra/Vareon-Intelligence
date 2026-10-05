"""Port dari `ScraperNewsWeb/app/routers/ta_groups.py`. Dua asimetri
port apa adanya dari kode lama, BUKAN keputusan baru:

1. Baca-vs-tulis: `GET /groups`, `GET /stats`, `GET /whitelist`,
   `GET /watchlist-names`, `GET /watchlist`, `GET /profile/{name}`,
   `GET /watchlist/navigator-layer` SEMUA gak `require_auth` -- sama pola
   kayak `articles.py`/`pir.py` dkk.
2. Client-scoping watchlist BACA: `GET /watchlist-names`/`GET /watchlist`/
   `GET /watchlist/navigator-layer` pakai `x_client_id or "default"`
   LANGSUNG (bukan `effective_client_id`) -- karena endpoint-endpoint itu
   emang gak punya `user` (gak ada auth buat divalidasi header-nya
   terhadap). Efeknya: header `X-Client-ID` sembarang diterima apa
   adanya buat baca. `POST`/`DELETE /watchlist` (perlu auth) TETAP pakai
   `effective_client_id` yang tervalidasi. Port apa adanya, sama alasan
   kayak asimetri client-scoping di `rfi.py`/`pir.py`.

QA 2026-10-05: catatan 'tanpa require_auth' di atas SUDAH TIDAK BERLAKU -- semua endpoint router ini
sekarang wajib login (`require_auth`). Pengecualian: `GET /watchlist/navigator-layer`
(dibuka dari ATT&CK Navigator eksternal) masih publik -- perlu keputusan terpisah.
"""

from __future__ import annotations

import re

from cti_core.db.models.ta import TAWhitelistEntry
from cti_core.db.models.threat_reference import ThreatActorGroup
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.ta import AsyncTAProfileRepo, AsyncTARepo
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, effective_client_id, get_db, request_ip, require_auth
from cti_api.schemas.ta_group import (
    TAGroupAdd,
    TAGroupListResponse,
    TAGroupOut,
    TAWatchlistListResponse,
    TAWatchlistOut,
    TAWhitelistListResponse,
    TAWhitelistOut,
)

_TECH_RE = re.compile(r"\b(T\d{4}(?:\.\d{3})?)\b")

router = APIRouter(prefix="/api/ta", tags=["threat-actor-groups"])


def _group_out(g: ThreatActorGroup) -> TAGroupOut:
    return TAGroupOut(
        id=g.id, name=g.name, added_date=g.created_at.date().isoformat(), source=g.source
    )


def _whitelist_out(w: TAWhitelistEntry) -> TAWhitelistOut:
    return TAWhitelistOut(id=w.id, name=w.name, added_date=w.added_date.date().isoformat())


@router.get("/groups", response_model=TAGroupListResponse, dependencies=[Depends(require_auth)])
async def get_ta_groups(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = Query("name"),
    sort_dir: str = Query("asc"),
    session: AsyncSession = Depends(get_db),
) -> TAGroupListResponse:
    groups, total = await AsyncTARepo(session).list_groups(
        search=search, page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir
    )
    return TAGroupListResponse(
        groups=[_group_out(g) for g in groups], total=total, page=page, page_size=page_size
    )


@router.get("/stats", dependencies=[Depends(require_auth)])
async def ta_stats(session: AsyncSession = Depends(get_db)) -> dict[str, object]:
    return await AsyncTARepo(session).get_ta_stats()


@router.post("/groups", dependencies=[Depends(require_auth)])
async def post_ta_group(
    body: TAGroupAdd,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    result = await AsyncTARepo(session).add_group(body.name)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="add_ta_group",
        target_id=body.name,
        ip_address=request_ip(request),
    )
    await session.commit()
    return result


@router.delete("/groups/{group_id}", dependencies=[Depends(require_auth)])
async def delete_ta_group(
    group_id: int,
    group_name: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    result = await AsyncTARepo(session).delete_group(group_id, group_name)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="delete_ta_group",
        target_id=group_name,
        ip_address=request_ip(request),
    )
    await session.commit()
    return result


@router.get(
    "/whitelist", response_model=TAWhitelistListResponse, dependencies=[Depends(require_auth)]
)
async def get_whitelist(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = Query("name"),
    sort_dir: str = Query("asc"),
    session: AsyncSession = Depends(get_db),
) -> TAWhitelistListResponse:
    items, total = await AsyncTARepo(session).list_whitelist(
        search=search, page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir
    )
    return TAWhitelistListResponse(
        items=[_whitelist_out(w) for w in items], total=total, page=page, page_size=page_size
    )


@router.delete("/whitelist/{name}", dependencies=[Depends(require_auth)])
async def restore_from_whitelist(
    name: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    ok = await AsyncTARepo(session).remove_from_whitelist(name)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="remove_whitelist",
        target_id=name,
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"success": ok}


@router.get("/watchlist-names", dependencies=[Depends(require_auth)])
async def get_ta_watchlist_names(
    x_client_id: str | None = Header(None), session: AsyncSession = Depends(get_db)
) -> dict[str, list[str]]:
    cid = x_client_id or "default"
    names = await AsyncTARepo(session).get_watchlist_names(cid)
    return {"names": names}


@router.get(
    "/watchlist", response_model=TAWatchlistListResponse, dependencies=[Depends(require_auth)]
)
async def get_ta_watchlist(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = Query("name"),
    sort_dir: str = Query("asc"),
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> TAWatchlistListResponse:
    cid = x_client_id or "default"
    repo = AsyncTARepo(session)
    items, total = await repo.list_watchlist(
        client_id=cid,
        search=search,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    names = [item.name for item in items]
    dormancy = await AsyncTAProfileRepo(session).get_dormancy_states(names)
    return TAWatchlistListResponse(
        items=[
            TAWatchlistOut(
                id=i.id,
                name=i.name,
                added_date=i.created_at.date().isoformat(),
                dormancy_state=dormancy.get(i.name, "DORMANT"),
            )
            for i in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{actor}/timeline", dependencies=[Depends(require_auth)])
async def get_actor_timeline(
    actor: str,
    request: Request,
    months: int = Query(24, ge=3, le=60),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="ta_timeline_view",
        target_id=actor,
        ip_address=request_ip(request),
    )
    await session.commit()
    return await AsyncTAProfileRepo(session).get_timeline(actor, months=months)


@router.post("/watchlist", dependencies=[Depends(require_auth)])
async def post_ta_watchlist(
    body: TAGroupAdd,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    cid = effective_client_id(user, x_client_id)
    result = await AsyncTARepo(session).add_to_watchlist(body.name, cid)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="add_watchlist",
        target_id=body.name,
        ip_address=request_ip(request),
    )
    await session.commit()
    return result


@router.delete("/watchlist/{name}", dependencies=[Depends(require_auth)])
async def delete_ta_watchlist(
    name: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, bool]:
    cid = effective_client_id(user, x_client_id)
    ok = await AsyncTARepo(session).remove_from_watchlist(name, cid)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="delete_watchlist",
        target_id=name,
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"success": ok}


class TAProfileGenerateBody(BaseModel):
    name: str


@router.post("/profile/generate", dependencies=[Depends(require_auth)])
async def post_ta_profile_generate(
    body: TAProfileGenerateBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    from cti_api.services.ta_profile import generate_ta_profile

    try:
        profile = await generate_ta_profile(session, body.name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="generate_ta_profile",
        target_id=body.name,
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"success": True, "profile": profile}


@router.get("/profile/{name}", dependencies=[Depends(require_auth)])
async def get_ta_profile_endpoint(
    name: str, session: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    from cti_api.services.ta_profile import get_ta_profile_enriched

    profile = await get_ta_profile_enriched(session, name)
    if profile is None:
        return {"exists": False, "profile": None}
    return {"exists": True, "profile": profile}


@router.get("/watchlist/navigator-layer")
async def watchlist_navigator_layer(
    x_client_id: str | None = Header(None), session: AsyncSession = Depends(get_db)
) -> JSONResponse:
    cid = x_client_id or "default"
    repo = AsyncTARepo(session)
    profile_repo = AsyncTAProfileRepo(session)
    names = await repo.get_watchlist_names(cid)

    tech_counts: dict[str, int] = {}
    tech_actors: dict[str, list[str]] = {}
    for name in names:
        row = await profile_repo.get_profile(name)
        if row is None:
            continue
        cap = (row.profile or {}).get("capability_assessment") or {}
        attack_techniques = cap.get("attack_techniques") or {}

        seen_for_actor: set[str] = set()
        for entries in attack_techniques.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, str):
                    continue
                for tid in _TECH_RE.findall(entry):
                    if tid in seen_for_actor:
                        continue
                    seen_for_actor.add(tid)
                    tech_counts[tid] = tech_counts.get(tid, 0) + 1
                    tech_actors.setdefault(tid, []).append(name)

    max_count = max(tech_counts.values(), default=1)

    techniques = []
    for tid, count in tech_counts.items():
        score = round((count / max_count) * 100)
        actor_list = ", ".join(tech_actors[tid])
        techniques.append(
            {
                "techniqueID": tid,
                "score": score,
                "comment": f"Used by: {actor_list}",
                "enabled": True,
                "showSubtechniques": False,
            }
        )

    layer = {
        "name": "Watchlist — TTP Coverage",
        "versions": {"attack": "14", "navigator": "4.9", "layer": "4.5"},
        "domain": "enterprise-attack",
        "description": (
            f"TTPs aggregated from {len(names)} watched threat actor profile(s). "
            "Score = actor coverage (darker = more actors use it)."
        ),
        "techniques": techniques,
        "gradient": {"colors": ["#ffe766", "#ff6666"], "minValue": 0, "maxValue": 100},
        "legendItems": [],
        "metadata": [],
        "showTacticRowBackground": True,
        "tacticRowBackground": "#1a1a2e",
        "selectTechniquesAcrossTactics": True,
    }
    return JSONResponse(content=layer)
