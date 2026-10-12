"""Port dari `ScraperNewsWeb/app/routers/newsletter.py`. `GET /source-hints`
SENGAJA gak `require_auth` -- port apa adanya, sama pola asimetri
baca-vs-tulis kayak router lain (`articles.py` dkk). Email beneran
dikirim lewat `cti_alerts.mailer.create_graph_draft` (Graph draft
API, BUKAN `/sendMail` -- lihat docstring modul itu), bukan SMTP (lihat
alasan di sana juga).

QA 2026-10-05: catatan 'tanpa require_auth' di atas SUDAH TIDAK BERLAKU -- `GET /source-hints`
sekarang wajib login (`require_auth`).

Alur (ROADMAP #22, PR 5): `preview` dan `draft-email` sama-sama membangun dari cache ringkasan.
`preview` TIDAK membuat baris `newsletters` dan tidak menulis IOC/sebutan CVE; `draft-email`
membuat draft Outlook DULU, baru menyimpan baris + IOC + sebutan CVE. Satu draft = satu baris,
dan draft yang gagal di Graph tidak meninggalkan baris.

Logo (ROADMAP #22, PR template): HTML yang dikirim dan disimpan merujuk logo lewat `cid:`, jadi
tiap jalur yang MENAMPILKAN HTML (preview, `GET /{id}/html`) memetakannya ke data URI, dan tiap
jalur yang MENGIRIM (`draft-email`, `resend`) melampirkannya lagi (`services/newsletter_logo.py`).
Subject dibangun SATU helper (`newsletter_edition.newsletter_subject`) untuk `draft-email` dan
`resend`.

Saran konten (ROADMAP #22, PR 7): `GET /suggestion` membaca saran tersimpan (terbaru, atau jendela
tertentu) dan `POST /suggestion/rebuild` membangun ulang satu jendela dengan tangan, menimpa saran
jendela itu. Keduanya hanya membaca/menulis tabel `newsletter_suggestions`; saran tidak pernah
mengirim atau membuat draft apa pun sendiri.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

import structlog
from cti_alerts.mailer import create_graph_draft
from cti_core.db.models.newsletter import NewsletterSuggestion
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, get_db, request_ip, require_auth
from cti_api.routers.articles import _serialize as _serialize_article
from cti_api.schemas.newsletter import (
    NewsletterListItem,
    NewsletterListResponse,
    NewsletterSectionsBody,
    NewsletterSuggestionItem,
    NewsletterSuggestionReason,
    NewsletterSuggestionRebuildBody,
    NewsletterSuggestionResponse,
)
from cti_api.services import newsletter as newsletter_service
from cti_api.services import newsletter_edition, newsletter_logo, newsletter_suggestion

router = APIRouter(prefix="/api/newsletter", tags=["newsletter"])
log = structlog.get_logger()


async def _resolve_sections(
    session: AsyncSession, body: NewsletterSectionsBody
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    """Id di request -> dict artikel per tier: (highlights, kartu penuh per section, compact per
    section). Batas jumlah ada di `newsletter_edition` (400), artikel yang tidak ada 404."""
    try:
        plan = newsletter_edition.plan_sections(body)
    except newsletter_edition.SectionLimitError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    articles = await newsletter_service.fetch_articles_by_ids(session, plan.all_ids)

    def _get(aid: int) -> dict[str, Any]:
        if aid not in articles:
            raise HTTPException(status_code=404, detail=f"Article {aid} not found")
        return articles[aid]

    return (
        [_get(i) for i in plan.highlights],
        {section: [_get(i) for i in ids] for section, ids in plan.full.items()},
        {section: [_get(i) for i in ids] for section, ids in plan.compact.items()},
    )


async def _build(session: AsyncSession, body: NewsletterSectionsBody) -> tuple[dict[str, Any], str]:
    """Konteks + HTML dari cache ringkasan (miss = fetch + LLM, lalu disimpan).

    Commit di sini HANYA menyimpan dua cache (ringkasan dan hint paywall); tidak ada baris
    `newsletters`, IOC, atau sebutan CVE yang ikut. Commit-nya sebelum render dan sebelum Graph
    supaya kerja fetch + LLM tidak hilang kalau langkah sesudahnya gagal: coba lagi tinggal
    memakai cache."""
    highlights, full, compact = await _resolve_sections(session, body)
    context = await newsletter_service.build_newsletter_context(
        session,
        highlights,
        full["apac"],
        full["global_news"],
        full["indonesia"],
        custom_css=body.custom_css,
        custom_intro=body.custom_intro,
        custom_footer=body.custom_footer,
        notes=body.notes,
        include_clusters=body.include_clusters,
        cluster_days=body.cluster_days,
        compact=compact,
        period_start=body.period_start,
        period_end=body.period_end,
        regenerate=body.regenerate,
        language=body.language,
    )
    await session.commit()
    return context, newsletter_service.render_newsletter_html(context)


@router.get("/source-hints", dependencies=[Depends(require_auth)])
async def source_hints(session: AsyncSession = Depends(get_db)) -> dict[str, dict[str, object]]:
    return await AsyncNewsletterRepo(session).get_all_paywall_hints()


@router.get("/history", response_model=NewsletterListResponse)
async def newsletter_history(
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> NewsletterListResponse:
    rows, total = await AsyncNewsletterRepo(session).list_all(page=page, page_size=page_size)
    return NewsletterListResponse(
        newsletters=[
            NewsletterListItem(
                id=r.id,
                week=r.week,
                year=r.year,
                label=newsletter_edition.edition_label(
                    r.period_start, r.period_end, r.week, r.year
                ),
                period_start=r.period_start,
                period_end=r.period_end,
                generated_at=r.generated_at,
                created_by=r.created_by,
                created_at=r.created_at.isoformat(),
                sections=r.sections,
            )
            for r in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _suggestion_response(
    session: AsyncSession, row: NewsletterSuggestion
) -> NewsletterSuggestionResponse:
    """Baris saran -> respons, dengan tiap item membawa artikelnya (`ArticleOut`, bentuk yang sama
    dengan antrean composer) supaya composer tidak perlu mengambil artikel satu per satu. Item
    yang artikelnya sudah terhapus dilewati: `items` tidak punya FK, dan artikel yang hilang tidak
    bisa masuk newsletter."""
    articles = AsyncArticleRepo(session)
    stored = sorted(row.items, key=lambda item: item["rank"])
    found = await articles.get_by_ids([item["article_id"] for item in stored])
    items = []
    for item in stored:
        article = found.get(item["article_id"])
        if article is None:
            continue
        items.append(
            NewsletterSuggestionItem(
                article_id=item["article_id"],
                section=item["section"],
                tier=item["tier"],
                rank=item["rank"],
                reasons=[NewsletterSuggestionReason.model_validate(r) for r in item["reasons"]],
                article=_serialize_article(article, articles.to_dict(article)),
            )
        )
    return NewsletterSuggestionResponse(
        id=row.id,
        period_start=row.period_start,
        period_end=row.period_end,
        label=newsletter_edition.period_label(row.period_start, row.period_end),
        items=items,
        summary_text=row.summary_text,
        summary_meta=row.summary_meta,
        created_at=row.created_at.isoformat(),
    )


@router.get("/suggestion", response_model=NewsletterSuggestionResponse)
async def get_suggestion(
    period_start: datetime.date | None = None,
    period_end: datetime.date | None = None,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> NewsletterSuggestionResponse:
    """Saran konten edisi newsletter. Tanpa parameter: edisi yang berakhir paling akhir. Dengan
    `period_start` + `period_end`: saran untuk jendela PERSIS itu. 404 kalau belum ada."""
    if (period_start is None) != (period_end is None):
        raise HTTPException(
            status_code=422, detail="set both period_start and period_end, or neither"
        )
    repo = AsyncNewsletterRepo(session)
    if period_start is not None and period_end is not None:
        row = await repo.get_suggestion(period_start, period_end)
    else:
        row = await repo.latest_suggestion()
    if row is None:
        raise HTTPException(status_code=404, detail="No newsletter suggestion found")
    return await _suggestion_response(session, row)


@router.post("/suggestion/rebuild", response_model=NewsletterSuggestionResponse)
async def rebuild_suggestion(
    request: Request,
    body: NewsletterSuggestionRebuildBody | None = None,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> NewsletterSuggestionResponse:
    """Bangun ulang saran satu jendela dengan tangan dan TIMPA saran tersimpan untuk jendela itu.
    Tanpa body (atau tanpa tanggal): bulan kalender sebelumnya menurut zona laporan (WIB).
    Dipakai analis kalau task terjadwal terlambat, atau data berubah setelah saran dibangun."""
    if body is not None and body.period_start is not None and body.period_end is not None:
        period_start, period_end = body.period_start, body.period_end
    else:
        period_start, period_end = newsletter_suggestion.default_window()
    row = await newsletter_suggestion.build_suggestion(session, period_start, period_end)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="rebuild_newsletter_suggestion",
        target_id=str(row.id),
        detail={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "items": len(row.items),
        },
        ip_address=request_ip(request),
    )
    await session.commit()
    return await _suggestion_response(session, row)


@router.get("/{newsletter_id}/html")
async def get_saved_html(
    newsletter_id: int,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> HTMLResponse:
    html = await AsyncNewsletterRepo(session).get_html(newsletter_id)
    if not html:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    return HTMLResponse(content=newsletter_logo.with_data_uris(html))


@router.post("/{newsletter_id}/resend")
async def resend_newsletter(
    newsletter_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    repo = AsyncNewsletterRepo(session)
    doc = await repo.get_by_id(newsletter_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    subject = newsletter_edition.newsletter_subject(
        doc.period_start, doc.period_end, doc.week, doc.year
    )
    try:
        email_id = await asyncio.to_thread(
            create_graph_draft,
            doc.html,
            subject,
            inline_images=newsletter_logo.inline_images_for(doc.html),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="resend_newsletter",
        target_id=str(newsletter_id),
        detail={"week": doc.week, "year": doc.year, "method": "graph"},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"email_id": email_id, "method": "graph", "subject": subject}


@router.post("/preview")
async def preview_newsletter(
    body: NewsletterSectionsBody,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    """Pratinjau tanpa efek ke catatan: tidak ada baris `newsletters` (jadi `newsletter_id`
    selalu null), tidak ada IOC, tidak ada sebutan CVE. Hanya dua cache yang terisi.

    `html` = versi untuk browser (logo sebagai data URI). `html_bytes` dan `size_warning` mengukur
    versi `cid:` yang akan DIKIRIM, bukan `html` ini; `size_warning` null di bawah ~90 KB."""
    try:
        context, html = await _build(session, body)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    html_bytes = newsletter_service.html_size_bytes(html)
    return {
        "html": newsletter_logo.with_data_uris(html),
        "html_bytes": html_bytes,
        "size_warning": newsletter_service.size_warning(html_bytes),
        "week": context["week"],
        "year": context["year"],
        "newsletter_id": None,
    }


@router.post("/draft-email")
async def draft_email(
    body: NewsletterSectionsBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    """Satu-satunya tempat edisi disimpan: bangun dari cache -> draft Outlook (Graph) -> baru
    simpan baris, IOC, sebutan CVE, dan audit dalam satu commit. Dulu barisnya di-commit SEBELUM
    Graph dipanggil, jadi Graph yang gagal meninggalkan baris histori tanpa draft."""
    try:
        context, html = await _build(session, body)
        subject = newsletter_edition.newsletter_subject(
            context["period_start"], context["period_end"], context["week"], context["year"]
        )
        email_id = await asyncio.to_thread(
            create_graph_draft,
            html,
            subject,
            inline_images=newsletter_logo.inline_images_for(html),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    try:
        newsletter_id = await newsletter_service.save_newsletter(
            session, context, html, user["username"]
        )
        await newsletter_service.write_article_findings(session, context)
        await AsyncAuditLogRepo(session).write(
            username=user["username"],
            action="draft_newsletter_email",
            target_id=str(newsletter_id),
            detail={"week": context["week"], "year": context["year"], "method": "graph"},
            ip_address=request_ip(request),
        )
        await session.commit()
    except Exception as e:
        await session.rollback()
        # Draft SUDAH ada di Outlook tapi barisnya tidak: id Graph-nya dicatat supaya draft itu
        # bisa dicari, dan dikembalikan ke analis supaya tidak membuat draft kedua.
        log.exception(
            "newsletter_draft_unsaved",
            email_id=email_id,
            week=context["week"],
            year=context["year"],
            created_by=user["username"],
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"The Outlook draft was created (Graph message id {email_id}) but saving the "
                f"newsletter history failed: {e}"
            ),
        ) from e
    return {
        "email_id": email_id,
        "method": "graph",
        "subject": subject,
        "week": context["week"],
        "year": context["year"],
        "newsletter_id": newsletter_id,
    }
