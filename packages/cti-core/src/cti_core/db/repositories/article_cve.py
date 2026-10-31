"""ArticleCveRepo -- relasi artikel -> CVE, kini mention `vulnerability` di `entity_mentions`
(P7c Task 8; `article_cves` tinggal view kompatibilitas). Entitas CVE: nama = `external_id` =
id CVE huruf besar, `in_title` di `extracted`."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.repositories.entity import CVE
from cti_core.db.repositories.entity import mention_rows as live_mentions
from cti_core.entity.mentions import (
    MentionInput,
    cve_mention,
    insert_mentions,
    mention_rows,
    resolve_all,
    resolve_all_async,
    touch_seen_async,
)

_METHOD = "explicit"
"""Id CVE tertulis eksplisit di teks (regex), bukan tebakan."""


def _hits(cve_ids: Iterable[str], title: str) -> list[MentionInput]:
    title_up = title.upper()
    unique = sorted({c.strip().upper() for c in cve_ids if c.strip()})
    return [h for c in unique if (h := cve_mention(c, _METHOD, in_title=c in title_up))]


def _ids_stmt(article_ids: Sequence[int]) -> Select[tuple[int | None, str]]:
    # entitas hidup saja (`mention_rows`); id CVE = `external_id` = nama entitas
    m = live_mentions(CVE)
    return select(m.c.article_id, m.c.name).where(m.c.article_id.in_(article_ids))


def _group(rows: Iterable[Any]) -> dict[int, set[str]]:
    found: dict[int, set[str]] = {}
    for article_id, cve_id in rows:
        found.setdefault(article_id, set()).add(cve_id)
    return found


class ArticleCveRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_many(self, article_id: int, cve_ids: Iterable[str], title: str) -> None:
        """Insert-ignore: pasangan yang sudah ada dibiarkan (idempotent saat replay)."""
        hits = _hits(cve_ids, title)
        rows = mention_rows({"article_id": article_id}, resolve_all(self.session, hits))
        if rows:
            self.session.execute(insert_mentions(rows, update=False))

    def cve_ids_by_article(self, article_ids: Sequence[int]) -> dict[int, set[str]]:
        """Id CVE (huruf besar) per artikel; artikel tanpa CVE tidak ada di hasil."""
        if not article_ids:
            return {}
        return _group(self.session.execute(_ids_stmt(article_ids)).all())


class AsyncArticleCveRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_many(self, article_id: int, cve_ids: Iterable[str], title: str) -> None:
        hits = _hits(cve_ids, title)
        rows = mention_rows(
            {"article_id": article_id},
            await resolve_all_async(self.session, hits),
        )
        if rows:
            await self.session.execute(insert_mentions(rows, update=False))
            # jalur sync (persist) memperbarui seen sesudah semua mention; jalur async berdiri
            # sendiri, jadi memperbaruinya di sini
            await touch_seen_async(self.session, article_id)

    async def cve_ids_by_article(self, article_ids: Sequence[int]) -> dict[int, set[str]]:
        """Id CVE (huruf besar) per artikel; artikel tanpa CVE tidak ada di hasil."""
        if not article_ids:
            return {}
        return _group((await self.session.execute(_ids_stmt(article_ids))).all())
