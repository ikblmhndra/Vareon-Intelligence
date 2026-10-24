"""ArticleCveRepo -- jalur tulis/baca `article_cves` (relasi artikel -> CVE)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.models.article_cve import ArticleCve


def _rows(article_id: int, cve_ids: Iterable[str], title: str) -> list[dict[str, object]]:
    title_up = title.upper()
    unique = {c.strip().upper() for c in cve_ids if c.strip()}
    return [
        {"article_id": article_id, "cve_id": c, "in_title": c in title_up} for c in sorted(unique)
    ]


class ArticleCveRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_many(self, article_id: int, cve_ids: Iterable[str], title: str) -> None:
        """Insert-ignore: pasangan yang sudah ada dibiarkan (idempotent saat replay)."""
        rows = _rows(article_id, cve_ids, title)
        if rows:
            self.session.execute(pg_insert(ArticleCve).values(rows).on_conflict_do_nothing())


class AsyncArticleCveRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_many(self, article_id: int, cve_ids: Iterable[str], title: str) -> None:
        rows = _rows(article_id, cve_ids, title)
        if rows:
            await self.session.execute(pg_insert(ArticleCve).values(rows).on_conflict_do_nothing())

    async def cve_ids_by_article(self, article_ids: Sequence[int]) -> dict[int, set[str]]:
        """Id CVE (huruf besar) per artikel; artikel tanpa CVE tidak ada di hasil."""
        if not article_ids:
            return {}
        result = await self.session.execute(
            select(ArticleCve.article_id, ArticleCve.cve_id).where(
                ArticleCve.article_id.in_(article_ids)
            )
        )
        found: dict[int, set[str]] = {}
        for article_id, cve_id in result.all():
            found.setdefault(article_id, set()).add(cve_id)
        return found
