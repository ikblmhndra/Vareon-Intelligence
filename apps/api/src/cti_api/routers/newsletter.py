"""Port dari `ScraperNewsWeb/app/routers/newsletter.py`. `GET /source-hints`
SENGAJA gak `require_auth` -- port apa adanya, sama pola asimetri
baca-vs-tulis kayak router lain (`articles.py` dkk). Email beneran
dikirim lewat `cti_alerts.mailer.create_graph_draft` (Graph draft
API, BUKAN `/sendMail` -- lihat docstring modul itu), bukan SMTP (lihat
alasan di sana juga).

QA 2026-10-05: catatan 'tanpa require_auth' di atas SUDAH TIDAK BERLAKU -- `GET /source-hints`
sekarang wajib login (`require_auth`).
"""

from __future__ import annotations

import asyncio

from cti_alerts.mailer import create_graph_draft
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, get_db, request_ip, require_auth
from cti_api.schemas.newsletter import (
    NewsletterListItem,
    NewsletterListResponse,
    NewsletterSectionsBody,
)
from cti_api.services import newsletter as newsletter_service

router = APIRouter(prefix="/api/newsletter", tags=["newsletter"])


async def _resolve_sections(
    session: AsyncSession, body: NewsletterSectionsBody
) -> tuple[
    dict[str, object], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]
]:
    if len(body.apac) > 5:
        raise HTTPException(status_code=400, detail="apac: max 5 articles")
    if len(body.global_news) > 5:
        raise HTTPException(status_code=400, detail="global_news: max 5 articles")
    if len(body.indonesia) > 5:
        raise HTTPException(status_code=400, detail="indonesia: max 5 articles")

    all_ids = [body.highlight, *body.apac, *body.global_news, *body.indonesia]
    articles = await newsletter_service.fetch_articles_by_ids(session, all_ids)

    def _get(aid: int) -> dict[str, object]:
        if aid not in articles:
            raise HTTPException(status_code=404, detail=f"Article {aid} not found")
        return articles[aid]

    return (
        _get(body.highlight),
        [_get(i) for i in body.apac],
        [_get(i) for i in body.global_news],
        [_get(i) for i in body.indonesia],
    )


async def _build_and_save(
    session: AsyncSession, body: NewsletterSectionsBody, created_by: str
) -> tuple[dict[str, object], str, int]:
    highlight, apac, global_news, indonesia = await _resolve_sections(session, body)
    context = await newsletter_service.build_newsletter_context(
        session,
        highlight,
        apac,
        global_news,
        indonesia,
        custom_css=body.custom_css,
        custom_intro=body.custom_intro,
        custom_footer=body.custom_footer,
        notes=body.notes,
        include_clusters=body.include_clusters,
        cluster_days=body.cluster_days,
    )
    html = newsletter_service.render_newsletter_html(context)
    newsletter_id = await newsletter_service.save_newsletter(session, context, html, created_by)
    await session.commit()
    return context, html, newsletter_id


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


@router.get("/{newsletter_id}/html")
async def get_saved_html(
    newsletter_id: int,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> HTMLResponse:
    html = await AsyncNewsletterRepo(session).get_html(newsletter_id)
    if not html:
        raise HTTPException(status_code=404, detail="Newsletter not found")
    return HTMLResponse(content=html)


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
    subject = f"[CTI Newsletter] Threat Intelligence Digest — Week {doc.week}, {doc.year}"
    try:
        email_id = await asyncio.to_thread(create_graph_draft, doc.html, subject)
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
    try:
        context, html, newsletter_id = await _build_and_save(session, body, user["username"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {
        "html": html,
        "week": context["week"],
        "year": context["year"],
        "newsletter_id": newsletter_id,
    }


@router.post("/draft-email")
async def draft_email(
    body: NewsletterSectionsBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user: AuthedUser = Depends(require_auth),
) -> dict[str, object]:
    try:
        context, html, newsletter_id = await _build_and_save(session, body, user["username"])
        subject = (
            f"[CTI Newsletter] Threat Intelligence Digest — "
            f"Week {context['week']}, {context['year']}"
        )
        email_id = await asyncio.to_thread(create_graph_draft, html, subject)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="draft_newsletter_email",
        target_id=str(newsletter_id),
        detail={"week": context["week"], "year": context["year"], "method": "graph"},
        ip_address=request_ip(request),
    )
    await session.commit()
    return {
        "email_id": email_id,
        "method": "graph",
        "subject": subject,
        "week": context["week"],
        "year": context["year"],
        "newsletter_id": newsletter_id,
    }
