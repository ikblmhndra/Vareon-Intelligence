"""Port dari `ScraperNewsWeb/app/routers/mindmap.py`. SELURUH router ini
`require_auth` (per-endpoint, sama kayak kode lama). `feature_type`
"cluster" SENGAJA gak terdaftar di `BUILDERS` -- `_check_type` bakal
400 buat itu, sama kayak feature_type gak dikenal lainnya. Lihat
docstring `cti_api.services.mindmap` soal alasan (`cluster_service.py`
belum diport, di luar scope 27 router)."""

from __future__ import annotations

from cti_core.db.repositories.mindmap import AsyncMindmapRepo, get_display_syntax
from cti_core.db.repositories.pir import AsyncPIRRepo
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, effective_client_id, get_db, require_auth, require_permission
from cti_api.services.mindmap import BUILDERS, get_or_generate

router = APIRouter(
    prefix="/api/mindmap",
    tags=["mindmap"],
    dependencies=[Depends(require_permission("wisemap_access"))],
)


class SaveSyntaxRequest(BaseModel):
    syntax: str


def _check_type(feature_type: str) -> None:
    if feature_type not in BUILDERS:
        raise HTTPException(status_code=400, detail=f"Unknown feature type: {feature_type}")


async def _ensure_pir_access(
    session: AsyncSession, user: AuthedUser, x_client_id: str | None, feature_type: str, doc_id: str
) -> None:
    """PIR milik satu client; cache mindmap (`mindmaps`) disimpan global per `(feature_type,
    doc_id)`, jadi tanpa cek ini user client lain bisa membaca peta PIR (judul, kriteria, artikel
    yang cocok) cukup dengan menebak id (audit keamanan 2026-10-24). PIR client lain = 404, sama
    dengan PIR yang tidak ada."""
    if feature_type != "pir":
        return
    pir = await AsyncPIRRepo(session).get_by_id(int(doc_id)) if doc_id.isdigit() else None
    if pir is None or pir.client_id != effective_client_id(user, x_client_id):
        raise HTTPException(status_code=404, detail=f"{feature_type} {doc_id} not found")


@router.get("/{feature_type}/{doc_id}")
async def get_mindmap(
    feature_type: str,
    doc_id: str,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    _check_type(feature_type)
    await _ensure_pir_access(session, user, x_client_id, feature_type, doc_id)
    doc = await get_or_generate(session, feature_type, doc_id)
    await session.commit()
    if doc is None:
        raise HTTPException(status_code=404, detail=f"{feature_type} {doc_id} not found")

    return {
        "feature_type": feature_type,
        "doc_id": doc_id,
        "title": doc.title,
        "mermaid_syntax": doc.mermaid_syntax,
        "custom_syntax": doc.custom_syntax,
        "display_syntax": get_display_syntax(doc),
        "generated_at": doc.generated_at,
        "edited_at": doc.edited_at,
    }


@router.put("/{feature_type}/{doc_id}")
async def save_mindmap_edit(
    feature_type: str,
    doc_id: str,
    body: SaveSyntaxRequest,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    _check_type(feature_type)
    await _ensure_pir_access(session, user, x_client_id, feature_type, doc_id)
    repo = AsyncMindmapRepo(session)
    doc = await repo.get_cached(feature_type, doc_id)
    if not doc:
        raise HTTPException(
            status_code=404, detail=f"No mindmap found for {feature_type} {doc_id}. Generate first."
        )
    updated = await repo.save_custom_syntax(feature_type, doc_id, body.syntax)
    if not updated:
        raise HTTPException(status_code=500, detail="Save failed")
    await session.commit()
    return {
        "feature_type": feature_type,
        "doc_id": doc_id,
        "edited_at": updated.edited_at,
        "display_syntax": get_display_syntax(updated),
    }


@router.post("/{feature_type}/{doc_id}/regenerate")
async def regenerate_mindmap(
    feature_type: str,
    doc_id: str,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> dict[str, object]:
    _check_type(feature_type)
    await _ensure_pir_access(session, user, x_client_id, feature_type, doc_id)
    result = await BUILDERS[feature_type](session, doc_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"{feature_type} {doc_id} not found")

    title, syntax = result
    doc = await AsyncMindmapRepo(session).save(feature_type, doc_id, title, syntax)
    await session.commit()

    return {
        "feature_type": feature_type,
        "doc_id": doc_id,
        "title": doc.title,
        "mermaid_syntax": doc.mermaid_syntax,
        "custom_syntax": None,
        "display_syntax": syntax,
        "generated_at": doc.generated_at,
    }
