"""Port `ScraperNewsWeb/app/routers/stix.py`. Builder-nya sendiri ada di
`cti_api.services.stix` (digabung sama `stix_service.py` lama -- lihat
docstring modul itu, gak ada tabel baru).

**Asimetri auth port apa adanya:** cuma `GET /article/{id}` yang
`require_auth`, tiga endpoint lain (`/ta/{name}`, `/iocs`, `/pirs`) publik
-- sama persis kode lama, sama pola asimetri baca-vs-tulis yang udah
konsisten di router lain (`newsletter.source_hints`, dst), bukan kelalaian
porting.

`article_id` sekarang `int` (Postgres bigint), bukan Mongo ObjectId hex
string -- penyesuaian skema yang sama kayak `iocs.py`/`newsletter.py`.
FastAPI udah nge-reject path non-integer duluan (422 Unprocessable
Entity), jadi try/except parse ObjectId yang ada di kode lama gak
relevan lagi di sini; filename export juga gak perlu potong 12 karakter
awal (`article_id[:12]`) karena int selalu pendek.

QA 2026-10-05: catatan 'tanpa require_auth' di atas SUDAH TIDAK BERLAKU -- semua endpoint router ini
sekarang wajib login (`require_auth`).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, get_db, require_auth
from cti_api.services import stix as stix_service

router = APIRouter(prefix="/api/stix", tags=["stix"], dependencies=[Depends(require_auth)])


def _today() -> str:
    return date.today().isoformat()


def _stix_response(bundle: dict[str, Any], filename: str) -> JSONResponse:
    """Balikin bundle STIX sebagai attachment JSON yang bisa didownload."""
    return JSONResponse(
        content=bundle,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/article/{article_id}",
    summary="Export STIX 2.1 bundle for a single article",
    response_class=JSONResponse,
)
async def export_article_stix(
    article_id: int,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> JSONResponse:
    """Build dan balikin bundle STIX 2.1 berisi report object buat
    artikelnya, TTP-nya sebagai attack-pattern, dan threat-actor stub,
    dengan relationship yang menghubungkan actor ke teknik.

    Balikin HTTP 404 kalau artikelnya gak ketemu."""
    bundle = await stix_service.build_article_stix_bundle(session, article_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Article '{article_id}' not found.")
    filename = f"stix-article-{article_id}-{_today()}.json"
    return _stix_response(bundle, filename)


@router.get(
    "/ta/{actor_name}",
    summary="Export STIX 2.1 bundle for a Threat Actor profile",
    response_class=JSONResponse,
)
async def export_ta_stix(actor_name: str, session: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Build dan balikin bundle STIX 2.1 berisi threat-actor object,
    attack-pattern (TTP), malware, dan indicator IOC yang diekstrak dari
    profil TA tersimpan buat *actor_name*.

    Balikin HTTP 404 kalau gak ada profil buat nama actor itu."""
    bundle = await stix_service.build_ta_stix_bundle(session, actor_name)

    # Kalau cuma identity object doang yang ada, berarti profilnya gak ketemu.
    stix_objects = bundle.get("objects", [])
    non_identity = [o for o in stix_objects if o.get("type") != "identity"]
    if not non_identity:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No TA profile found for actor '{actor_name}'. "
                "Generate one first via the TA Profiles endpoint."
            ),
        )

    safe_name = actor_name.replace(" ", "_").replace("/", "-")[:50]
    filename = f"stix-ta-{safe_name}-{_today()}.json"
    return _stix_response(bundle, filename)


@router.get(
    "/iocs",
    summary="Export STIX 2.1 bundle for IOC indicators",
    response_class=JSONResponse,
)
async def export_ioc_stix(
    type: str | None = Query(
        default=None,
        alias="type",
        description="Filter by IOC type (ip, domain, url, sha256, sha1, md5, email, cve)",
    ),
    limit: int = Query(
        default=500,
        ge=1,
        le=2000,
        description="Maximum number of IOCs to export (default 500, max 2000)",
    ),
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Ambil IOC dari database dan balikin sebagai objek indicator STIX
    2.1 di dalam satu bundle.

    Bisa difilter by IOC *type* dan dibatasin jumlahnya lewat *limit*."""
    bundle = await stix_service.build_ioc_stix_bundle(session, ioc_type=type, limit=limit)

    type_label = type if type else "all"
    filename = f"stix-iocs-{type_label}-{_today()}.json"
    return _stix_response(bundle, filename)


@router.get(
    "/pirs",
    summary="Export STIX 2.1 bundle for active PIRs",
    response_class=JSONResponse,
)
async def export_pir_stix(session: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Ambil semua Priority Intelligence Requirement aktif dari database
    dan wakilkan tiap satu sebagai objek course-of-action STIX 2.1 di
    dalam satu bundle."""
    bundle = await stix_service.build_pir_stix_bundle(session)
    filename = f"stix-pirs-{_today()}.json"
    return _stix_response(bundle, filename)
