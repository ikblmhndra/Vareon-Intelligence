"""AsyncNewsletterRepo -- port persistensi `newsletter_service.py`
(`save_newsletter`/`list_newsletters`/`get_newsletter_html`/
`get_newsletter_doc`) + `newsletter_paywall_hints`. Fase 7.3 (router
`newsletter`, Bagian 4).

Ekstraksi IOC (`extract_iocs`), fetch body (Playwright), LLM
summarization, dan HTML rendering (Jinja2) TETAP di `cti_api` (bukan di
sini) -- itu bukan concern database, `cti_api.services.newsletter` yang
nanganin."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.db.models.newsletter import (
    Newsletter,
    NewsletterArticleSummary,
    NewsletterPaywallHint,
)


class AsyncNewsletterRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(
        self,
        *,
        week: int,
        year: int,
        generated_at: str,
        created_by: str,
        html: str,
        sections: dict[str, Any],
        period_start: datetime.date | None = None,
        period_end: datetime.date | None = None,
    ) -> Newsletter:
        row = Newsletter(
            week=week,
            year=year,
            period_start=period_start,
            period_end=period_end,
            generated_at=generated_at,
            created_by=created_by,
            html=html,
            sections=sections,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_all(self, *, page: int = 1, page_size: int = 20) -> tuple[list[Newsletter], int]:
        total = (
            await self.session.execute(select(func.count()).select_from(Newsletter))
        ).scalar_one()
        # `.id.desc()` tie-breaker -- `created_at` (`func.now()`) balikin
        # nilai yang SAMA buat semua baris yang di-insert dalam satu
        # transaksi (Postgres: `now()` = transaction time, bukan
        # statement time), jadi `ORDER BY created_at` doang non-deterministik
        # begitu ada >1 newsletter dibikin cepet berturutan. Ketauan dari
        # test integrasi, bukan hipotesis.
        result = await self.session.execute(
            select(Newsletter)
            .order_by(Newsletter.created_at.desc(), Newsletter.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def get_by_id(self, newsletter_id: int) -> Newsletter | None:
        result = await self.session.execute(
            select(Newsletter).where(Newsletter.id == newsletter_id)
        )
        return result.scalar_one_or_none()

    async def get_html(self, newsletter_id: int) -> str | None:
        row = await self.get_by_id(newsletter_id)
        return row.html if row else None

    async def get_article_summary(
        self, article_id: int, language: str
    ) -> NewsletterArticleSummary | None:
        """Baris cache ringkasan untuk satu artikel + bahasa, atau None kalau belum ada.

        `populate_existing`: `upsert_article_summary` menulis lewat statement, bukan lewat objek
        ORM, jadi objek yang sudah dimuat sesi ini bisa basi; baca selalu dari baris sekarang."""
        result = await self.session.execute(
            select(NewsletterArticleSummary)
            .where(
                NewsletterArticleSummary.article_id == article_id,
                NewsletterArticleSummary.language == language,
            )
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_article_summaries(
        self, article_ids: Sequence[int], language: str
    ) -> dict[int, NewsletterArticleSummary]:
        """Sama, untuk banyak artikel sekaligus (baris compact). Yang belum ada tidak ikut."""
        if not article_ids:
            return {}
        result = await self.session.execute(
            select(NewsletterArticleSummary)
            .where(
                NewsletterArticleSummary.article_id.in_(article_ids),
                NewsletterArticleSummary.language == language,
            )
            .execution_options(populate_existing=True)
        )
        return {row.article_id: row for row in result.scalars().all()}

    async def upsert_article_summary(
        self,
        *,
        article_id: int,
        language: str,
        key_points: list[str],
        summary: str,
        body_source: str,
        iocs: dict[str, list[str]],
        cve_ids: list[str],
        model: str,
        token_usage: dict[str, int],
    ) -> None:
        """Simpan (atau timpa, untuk `regenerate`) cache satu artikel.

        `ON CONFLICT DO UPDATE`, bukan get-lalu-insert: dua preview bersamaan untuk artikel yang
        sama (klik ganda, dua analis) sama-sama miss, dan insert kedua akan kena unique
        constraint dan menjatuhkan seluruh request. Sekarang yang terakhir menang."""
        values = {
            "key_points": key_points,
            "summary": summary,
            "body_source": body_source,
            "iocs": iocs,
            "cve_ids": cve_ids,
            "model": model,
            "token_usage": token_usage,
        }
        stmt = pg_insert(NewsletterArticleSummary).values(
            article_id=article_id, language=language, **values
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["article_id", "language"],
            set_={**values, "created_at": func.now()},
        )
        await self.session.execute(stmt)

    async def get_paywall_hint(self, source: str) -> NewsletterPaywallHint | None:
        result = await self.session.execute(
            select(NewsletterPaywallHint).where(NewsletterPaywallHint.source == source)
        )
        return result.scalar_one_or_none()

    async def upsert_paywall_hint(self, source: str, *, last_seen: str) -> None:
        existing = await self.get_paywall_hint(source)
        if existing is not None:
            existing.paywall_likely = True
            existing.last_seen = last_seen
        else:
            self.session.add(
                NewsletterPaywallHint(source=source, paywall_likely=True, last_seen=last_seen)
            )
        await self.session.flush()

    async def get_all_paywall_hints(self) -> dict[str, dict[str, Any]]:
        result = await self.session.execute(
            select(NewsletterPaywallHint).where(NewsletterPaywallHint.paywall_likely.is_(True))
        )
        return {
            row.source: {"paywall_likely": True, "last_seen": row.last_seen}
            for row in result.scalars().all()
        }
