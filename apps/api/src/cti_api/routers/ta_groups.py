"""Port dari `ScraperNewsWeb/app/routers/ta_groups.py`. Dua asimetri kode lama dulu dipertahankan
apa adanya (baca tanpa `require_auth`; baca watchlist memakai header `X-Client-ID` mentah).
Dua-duanya SUDAH ditutup:

- QA 2026-10-05: semua endpoint router ini wajib login (`require_auth`).
- Audit 2026-10-21: `GET /watchlist-names` dan `GET /watchlist/navigator-layer` memakai
  `effective_client_id`, jadi `X-Client-ID` milik client lain
  diabaikan. `navigator-layer` tidak lagi publik (tadinya membaca watchlist client mana
  pun tanpa token); fetch lintas-situs dari ATT&CK Navigator eksternal tidak membawa token, jadi
  layer ini sekarang sama dengan `/api/mitre` dan `/api/attack/navigator-layer`: wajib login.

P7c-2: halaman Threat Actor Room dipensiunkan (diganti `/intelligence/entities`), jadi endpoint
grup/whitelist/watchlist (GET/POST/DELETE)/profile/timeline ikut dihapus. Yang tersisa hanya
`/stats` (dashboard), `/watchlist-names` (newsroom) dan `/watchlist/navigator-layer` (tab Actors).
"""

from __future__ import annotations

import re

from cti_core.db.repositories.ta import AsyncTAProfileRepo, AsyncTARepo
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    effective_client_id,
    get_db,
    require_auth,
    require_permission,
)

_TECH_RE = re.compile(r"\b(T\d{4}(?:\.\d{3})?)\b")

router = APIRouter(
    prefix="/api/ta",
    tags=["threat-actor-groups"],
    dependencies=[Depends(require_permission("view_ta"))],
)


@router.get("/stats", dependencies=[Depends(require_auth)])
async def ta_stats(session: AsyncSession = Depends(get_db)) -> dict[str, object]:
    return await AsyncTARepo(session).get_ta_stats()


@router.get("/watchlist-names", dependencies=[Depends(require_auth)])
async def get_ta_watchlist_names(
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, list[str]]:
    cid = effective_client_id(user, x_client_id)
    names = await AsyncTARepo(session).get_watchlist_names(cid)
    return {"names": names}


@router.get("/watchlist/navigator-layer", dependencies=[Depends(require_auth)])
async def watchlist_navigator_layer(
    x_client_id: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> JSONResponse:
    cid = effective_client_id(user, x_client_id)
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
