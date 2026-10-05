"""Port dari `ScraperNewsWeb/app/routers/pir.py`. Dua asimetri port apa
adanya dari kode lama, BUKAN keputusan baru di sini:

1. Baca-vs-tulis: `GET /options`, `GET /{id}/articles`, `GET /{id}/note`,
   `GET /{id}/export`, `GET /{id}/export/docx` SEMUA gak `require_auth`
   di kode lama -- cuma `POST`/`PUT`/`DELETE` yang di-gate. Sama pola
   kayak `articles.py`/`filtered_articles.py`.
2. Client-scoping: `GET ""` (list) dan `POST` (create) di-filter
   client_id, tapi `PUT`/`DELETE`/articles/notes/export SAMA SEKALI
   gak -- lihat docstring `cti_core.db.repositories.pir` buat detail.

Alert otomatis PIR (`check_new_articles_vs_pirs` lama) BELUM diport --
itu Fase 7.8 (Celery beat), bukan router CRUD ini.

QA 2026-10-05: catatan 'tanpa require_auth' di atas SUDAH TIDAK BERLAKU -- semua endpoint router ini
sekarang wajib login (`require_auth`).
"""

from __future__ import annotations

import datetime
import io
from typing import Any

from cti_core.db.models.article import Article
from cti_core.db.models.pir import PIRNote, PIRRequirement
from cti_core.db.repositories.article import AsyncArticleRepo, all_country_codes
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import (
    AuthedUser,
    effective_client_id,
    ensure_client_access,
    get_db,
    request_ip,
    require_auth,
)
from cti_api.schemas.pir import (
    PIRArticleListResponse,
    PIRArticleOut,
    PIRCreate,
    PIRCriteria,
    PIRNoteIn,
    PIRNoteOut,
    PIROptions,
    PIROut,
    PIRUpdate,
)
from cti_api.services.pir_docx import build_docx, export_filename

router = APIRouter(prefix="/api/pir", tags=["pir"], dependencies=[Depends(require_auth)])


def _to_out(pir: PIRRequirement, total: int, last_match: str | None, recent: int) -> PIROut:
    return PIROut(
        id=pir.id,
        title=pir.title,
        description=pir.description,
        priority=pir.priority,
        owner=pir.owner,
        status=pir.status,
        criteria=PIRCriteria.model_validate(pir.criteria),
        start_date=pir.start_date.isoformat() if pir.start_date else None,
        end_date=pir.end_date.isoformat() if pir.end_date else None,
        coverage_count=total,
        recent_coverage=recent,
        is_gap=total > 0 and recent == 0,
        last_match=last_match,
        created_at=pir.created_at.isoformat(),
        updated_at=pir.updated_at.isoformat(),
    )


def _article_out(article: Article, has_note: bool) -> PIRArticleOut:
    return PIRArticleOut(
        id=article.id,
        title=article.title,
        url=article.url,
        posted_on=article.posted_on.isoformat() if article.posted_on else None,
        source=article.source,
        news_type=article.news_type,
        threat_actors=[t.threat_actor for t in article.threat_actors],
        impacted_industries=[i.industry for i in article.industries],
        # Role apa pun -- PIR match negara lewat filter `countries` (role apa
        # pun), jadi negara yang bikin artikel ke-match harus ikut tampil.
        mentioned_countries=all_country_codes(article),
        has_note=has_note,
    )


def _article_export_dict(article: Article, note: PIRNote | None) -> dict[str, Any]:
    return {
        "_id": str(article.id),
        "title": article.title,
        "url": article.url,
        "posted_on": article.posted_on.isoformat() if article.posted_on else None,
        "source": article.source,
        "news_type": article.news_type,
        "threat_actors": [t.threat_actor for t in article.threat_actors],
        "impacted_industries": [i.industry for i in article.industries],
        "mentioned_countries": all_country_codes(article),
        "analyst_note": (
            {"note": note.note, "analyst": note.analyst, "updated_at": note.updated_at.isoformat()}
            if note
            else {}
        ),
    }


async def _get_pir_or_404(repo: AsyncPIRRepo, pir_id: int, user: AuthedUser) -> PIRRequirement:
    """PIR by id, hanya jika milik client user (superadmin: semua). Selain itu 404."""
    pir = await repo.get_by_id(pir_id)
    if pir is None:
        raise HTTPException(status_code=404, detail="PIR not found")
    ensure_client_access(user, pir.client_id)
    return pir


@router.get("/options", response_model=PIROptions)
async def pir_options(session: AsyncSession = Depends(get_db)) -> PIROptions:
    options = await AsyncPIRRepo(session).get_options(AsyncArticleRepo(session))
    return PIROptions(**options)


@router.get("", response_model=list[PIROut])
async def get_pirs(
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> list[PIROut]:
    cid = effective_client_id(user, x_client_id)
    rows = await AsyncPIRRepo(session).list_pirs(AsyncArticleRepo(session), cid)
    return [_to_out(*row) for row in rows]


@router.get("/{pir_id}/articles", response_model=PIRArticleListResponse)
async def pir_articles(
    pir_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> PIRArticleListResponse:
    repo = AsyncPIRRepo(session)
    pir = await _get_pir_or_404(repo, pir_id, user)
    articles, total = await repo.list_articles_for_pir(
        pir, AsyncArticleRepo(session), page=page, page_size=page_size
    )
    noted_urls = await repo.urls_with_notes(pir_id, [a.url for a in articles])
    return PIRArticleListResponse(
        articles=[_article_out(a, a.url in noted_urls) for a in articles],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{pir_id}/note", response_model=PIRNoteOut)
async def pir_get_note(
    pir_id: int,
    url: str = Query(...),
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> PIRNoteOut:
    repo = AsyncPIRRepo(session)
    await _get_pir_or_404(repo, pir_id, user)
    note = await repo.get_note(pir_id, url)
    if note is None:
        return PIRNoteOut(pir_id=pir_id, url=url, note="", analyst="", updated_at="")
    return PIRNoteOut(
        pir_id=note.pir_id,
        url=note.url,
        note=note.note,
        analyst=note.analyst,
        updated_at=note.updated_at.isoformat(),
    )


@router.put("/{pir_id}/note", response_model=PIRNoteOut)
async def pir_save_note(
    pir_id: int,
    body: PIRNoteIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> PIRNoteOut:
    repo = AsyncPIRRepo(session)
    await _get_pir_or_404(repo, pir_id, user)
    note = await repo.save_note(pir_id, body.url, body.note, body.analyst)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="save_pir_note",
        target_id=str(pir_id),
        detail={"url": body.url},
        ip_address=request_ip(request),
    )
    await session.commit()
    # `PIRNote.updated_at` juga server-computed (`onupdate=func.now()`) --
    # sama kayak `PIRRequirement.updated_at` di `put_pir`, refresh() wajib
    # kalau baris ini kena UPDATE (note yang udah ada), bukan INSERT baru.
    await session.refresh(note)
    return PIRNoteOut(
        pir_id=note.pir_id,
        url=note.url,
        note=note.note,
        analyst=note.analyst,
        updated_at=note.updated_at.isoformat(),
    )


async def _build_export_data(
    repo: AsyncPIRRepo, session: AsyncSession, pir: PIRRequirement
) -> dict[str, Any]:
    articles = await repo.list_all_articles_for_pir(pir, AsyncArticleRepo(session))
    notes_by_url = await repo.notes_by_url(pir.id)
    total, last_match, recent = await repo.compute_coverage(
        AsyncArticleRepo(session), pir.criteria, pir.start_date, pir.end_date
    )
    articles_out = [_article_export_dict(a, notes_by_url.get(a.url)) for a in articles]
    return {
        "pir": _to_out(pir, total, last_match, recent).model_dump(),
        "exported_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "total_articles": len(articles_out),
        "articles": articles_out,
    }


@router.get("/{pir_id}/export")
async def pir_export(
    pir_id: int,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, Any]:
    repo = AsyncPIRRepo(session)
    pir = await _get_pir_or_404(repo, pir_id, user)
    return await _build_export_data(repo, session, pir)


@router.get("/{pir_id}/export/docx")
async def pir_export_docx(
    pir_id: int,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> StreamingResponse:
    repo = AsyncPIRRepo(session)
    pir = await _get_pir_or_404(repo, pir_id, user)
    data = await _build_export_data(repo, session, pir)
    docx_bytes = build_docx(data)
    filename = export_filename(data["pir"].get("title", "PIR"), data["exported_at"])
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("", response_model=PIROut)
async def post_pir(
    body: PIRCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
    x_client_id: str | None = Header(None),
) -> PIROut:
    cid = effective_client_id(user, x_client_id)
    repo = AsyncPIRRepo(session)
    pir = await repo.create(body.model_dump(), client_id=cid)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="create_pir",
        detail={"title": body.title, "client_id": cid},
        ip_address=request_ip(request),
    )
    await session.commit()
    total, last_match, recent = await repo.compute_coverage(
        AsyncArticleRepo(session), pir.criteria, pir.start_date, pir.end_date
    )
    return _to_out(pir, total, last_match, recent)


@router.put("/{pir_id}", response_model=PIROut)
async def put_pir(
    pir_id: int,
    body: PIRUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> PIROut:
    repo = AsyncPIRRepo(session)
    await _get_pir_or_404(repo, pir_id, user)
    data = body.model_dump(exclude_none=True)
    pir = await repo.update(pir_id, data)
    if pir is None:
        raise HTTPException(status_code=404, detail="PIR not found")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="update_pir",
        target_id=str(pir_id),
        ip_address=request_ip(request),
    )
    await session.commit()
    # `updated_at` server-computed (`onupdate=func.now()`) -- flush() lewat
    # UPDATE gak selalu eager-fetch nilai barunya (beda dari INSERT di
    # `create()`, yang selalu dapet lewat RETURNING). Tanpa refresh() ini,
    # akses `pir.updated_at` di `_to_out()` trigger lazy-load implisit sync
    # yang gagal di sesi async (`MissingGreenlet`) -- kelas bug yang sama
    # kayak catatan `AsyncArticleRepo.set_enrichment`.
    await session.refresh(pir)
    total, last_match, recent = await repo.compute_coverage(
        AsyncArticleRepo(session), pir.criteria, pir.start_date, pir.end_date
    )
    return _to_out(pir, total, last_match, recent)


@router.delete("/{pir_id}")
async def remove_pir(
    pir_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, bool]:
    repo = AsyncPIRRepo(session)
    await _get_pir_or_404(repo, pir_id, user)
    ok = await repo.delete(pir_id)
    if not ok:
        raise HTTPException(status_code=404, detail="PIR not found")
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="delete_pir",
        target_id=str(pir_id),
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"deleted": True}
