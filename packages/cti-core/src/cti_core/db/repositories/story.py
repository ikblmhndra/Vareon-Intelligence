"""StoryRepo -- jalur tulis/baca `stories` (dedup berita sama saat ingest, P3).

Repo sync dipakai pipeline enrichment (Celery); repo async dipakai API. Dataclass di sini
data murni, dipakai ulang oleh resolver (`cti_enrich`) supaya resolver tidak menyentuh DB.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, bindparam, delete, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.models.article import Article
from cti_core.db.models.story import Story

STORY_LOCK_NAMESPACE = 7_311_002
"""Namespace kunci advisory resolver story; bersebelahan dengan `_URL_LOCK_NAMESPACE =
7_311_001` di `cti_enrich.pipeline` (kunci per-URL). Beda namespace supaya keduanya tidak
saling bentur."""

_ATTACH_SQL = text(
    """
    UPDATE stories SET
        article_count = article_count + 1,
        source_count = (SELECT count(DISTINCT source) FROM articles WHERE story_id = :id),
        last_seen_at = greatest(last_seen_at, :now),
        cve_ids = array(SELECT DISTINCT unnest(cve_ids || CAST(:cves AS text[]))),
        lead_article_id = coalesce(lead_article_id, :article_id),
        classify = coalesce(classify, CAST(:classify AS jsonb)),
        updated_at = now()
    WHERE id = :id
    """
).bindparams(bindparam("classify", type_=JSONB(none_as_null=True)))


@dataclass(frozen=True)
class StoryMember:
    title: str
    source: str


@dataclass(frozen=True)
class StoryCandidate:
    id: int
    cve_ids: frozenset[str]
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    members: list[StoryMember]
    """Anggota yang dipakai aturan judul. Story tanpa artikel punya satu anggota:
    judul + sumber lead-nya sendiri."""
    has_classify: bool


@dataclass(frozen=True)
class StoryStats:
    new_stories: int
    followups: int
    inherited: int


class StoryRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock(self) -> None:
        """Kunci advisory tingkat transaksi: satu resolver sekaligus, supaya dua artikel
        berita sama yang diproses bersamaan tidak membuat dua story."""
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(:ns, 0)"), {"ns": STORY_LOCK_NAMESPACE}
        )

    def candidates(
        self, now: datetime.datetime, *, window_hours: int, max_age_days: int
    ) -> list[StoryCandidate]:
        """Story terbuka: `last_seen_at` dalam jendela DAN `first_seen_at` belum lewat batas."""
        window_start = now - datetime.timedelta(hours=window_hours)
        age_start = now - datetime.timedelta(days=max_age_days)
        stories = (
            self.session.execute(
                select(Story).where(
                    and_(Story.last_seen_at >= window_start, Story.first_seen_at >= age_start)
                )
            )
            .scalars()
            .all()
        )
        if not stories:
            return []
        members: dict[int, list[StoryMember]] = {s.id: [] for s in stories}
        rows = self.session.execute(
            select(Article.story_id, Article.title, Article.source).where(
                Article.story_id.in_(list(members))
            )
        ).all()
        for story_id, title, source in rows:
            members[story_id].append(StoryMember(title=title, source=source))
        result: list[StoryCandidate] = []
        for s in stories:
            story_members = members[s.id] or [StoryMember(title=s.title, source=s.lead_source)]
            result.append(
                StoryCandidate(
                    id=s.id,
                    cve_ids=frozenset(s.cve_ids),
                    first_seen_at=s.first_seen_at,
                    last_seen_at=s.last_seen_at,
                    members=story_members,
                    has_classify=s.classify is not None,
                )
            )
        return result

    def create(self, *, title: str, source: str, cve_ids: set[str], now: datetime.datetime) -> int:
        story = Story(
            title=title,
            lead_source=source,
            cve_ids=sorted(cve_ids),
            first_seen_at=now,
            last_seen_at=now,
            article_count=0,
            source_count=0,
        )
        self.session.add(story)
        self.session.flush()
        return story.id

    def get_inherit(self, story_id: int) -> tuple[dict[str, Any] | None, int | None]:
        """(classify, lead_article_id) story; classify NULL = belum bisa diwariskan."""
        row = self.session.execute(
            select(Story.classify, Story.lead_article_id).where(Story.id == story_id)
        ).one_or_none()
        if row is None:
            return None, None
        return row[0], row[1]

    def attach(
        self,
        story_id: int,
        *,
        article_id: int,
        cve_ids: set[str],
        now: datetime.datetime,
        classify: dict[str, Any] | None,
    ) -> None:
        """Satu UPDATE atomik. `source_count` dihitung ulang dari `articles WHERE story_id`,
        jadi panggil SETELAH baris artikel ber-`story_id` di-flush."""
        self.session.execute(
            _ATTACH_SQL,
            {
                "id": story_id,
                "now": now,
                "cves": sorted(cve_ids),
                "article_id": article_id,
                "classify": classify,
            },
        )

    def discard_if_empty(self, story_id: int) -> bool:
        """Hapus story yang tidak punya artikel (lead ditolak/gagal sebelum persist)."""
        result = self.session.execute(
            delete(Story).where(Story.id == story_id, Story.article_count == 0)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def purge_empty(self, older_than: datetime.datetime) -> int:
        """Sapu story kosong yang dibuat sebelum `older_than` (sisa crash di tengah pipeline)."""
        result = self.session.execute(
            delete(Story).where(Story.article_count == 0, Story.created_at < older_than)
        )
        return int(result.rowcount)  # type: ignore[attr-defined]


class AsyncStoryRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def counts(self, ids: Sequence[int]) -> dict[int, tuple[int, int]]:
        """(article_count, source_count) per story; id yang tidak ada tidak masuk hasil."""
        if not ids:
            return {}
        result = await self.session.execute(
            select(Story.id, Story.article_count, Story.source_count).where(Story.id.in_(ids))
        )
        return {sid: (ac, sc) for sid, ac, sc in result.all()}

    async def stats_since(self, since: datetime.datetime) -> StoryStats:
        """Story baru, follow-up (artikel yang menempel ke story lewat cve/judul), dan berapa
        follow-up yang mewarisi classify."""
        new_stories = await self.session.scalar(
            select(func.count()).select_from(Story).where(Story.created_at >= since)
        )
        follow = and_(
            Article.created_at >= since,
            Article.story_match.in_(("cve", "title_exact", "title")),
        )
        followups = await self.session.scalar(
            select(func.count()).select_from(Article).where(follow)
        )
        inherited = await self.session.scalar(
            select(func.count())
            .select_from(Article)
            .where(follow, Article.raw_enrichment["classify"].has_key("inherited_from_story"))
        )
        return StoryStats(
            new_stories=int(new_stories or 0),
            followups=int(followups or 0),
            inherited=int(inherited or 0),
        )
