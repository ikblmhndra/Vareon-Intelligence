"""AsyncSourceReliabilityRepo -- CRUD `source_reliability_entries` (Fase
7.3, Bagian 2). Port dari `ScraperNewsWeb/app/services/
source_score_db_service.py`. Grading Admiralty manual analis, global (gak
ada client_id) -- lihat docstring `models/source_reliability.py`."""

from __future__ import annotations

import datetime
from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.confidence import DEFAULT_GRADES
from cti_core.db.models.article import Article
from cti_core.db.models.source_reliability import SourceReliabilityEntry

RELIABILITY_LABELS: dict[str, str] = {
    "A": "Completely reliable",
    "B": "Usually reliable",
    "C": "Fairly reliable",
    "D": "Not usually reliable",
    "E": "Unreliable",
    "F": "Cannot be judged",
}

CREDIBILITY_LABELS: dict[str, str] = {
    "1": "Confirmed by other sources",
    "2": "Probably true",
    "3": "Possibly true",
    "4": "Doubtful",
    "5": "Improbable",
    "6": "Cannot be judged",
}

_SORT_FIELDS = {
    "source_name": SourceReliabilityEntry.source_name,
    "analyst_name": SourceReliabilityEntry.analyst_name,
    "reliability_grade": SourceReliabilityEntry.reliability_grade,
    "credibility_code": SourceReliabilityEntry.credibility_code,
    "added_date": SourceReliabilityEntry.added_date,
    "last_updated": SourceReliabilityEntry.last_updated,
}


class SourceReliabilityRepo:
    """Versi sync (persist enrichment di worker) -- cuma lookup nama."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_name_ci(self, source_name: str) -> SourceReliabilityEntry | None:
        return self.session.execute(
            select(SourceReliabilityEntry).where(
                func.lower(SourceReliabilityEntry.source_name) == source_name.lower()
            )
        ).scalar_one_or_none()


class AsyncSourceReliabilityRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_entries(
        self,
        *,
        search: str | None = None,
        grade: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "source_name",
        sort_dir: str = "asc",
    ) -> tuple[list[SourceReliabilityEntry], int]:
        stmt = select(SourceReliabilityEntry)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(
                SourceReliabilityEntry.source_name.ilike(like)
                | SourceReliabilityEntry.analyst_name.ilike(like)
                | SourceReliabilityEntry.notes.ilike(like)
            )
        if grade:
            stmt = stmt.where(SourceReliabilityEntry.reliability_grade == grade.upper())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        order_col = _SORT_FIELDS.get(sort_by, SourceReliabilityEntry.source_name)
        order = order_col.desc() if sort_dir == "desc" else order_col.asc()
        list_stmt = stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(list_stmt)
        return list(result.scalars().all()), total

    async def get_by_name_ci(self, source_name: str) -> SourceReliabilityEntry | None:
        result = await self.session.execute(
            select(SourceReliabilityEntry).where(
                func.lower(SourceReliabilityEntry.source_name) == source_name.lower()
            )
        )
        return result.scalar_one_or_none()

    async def ensure_defaults(self, sources: Mapping[str, str]) -> list[str]:
        """`{nama sumber: content_kind}` -> baris `origin='default'` untuk yang belum ada
        (case-insensitive), grade dari `DEFAULT_GRADES`. Baris yang sudah ada (analis atau default
        lama) TIDAK pernah disentuh. Balikin nama yang baru dimasukkan. Flush saja, commit di
        pemanggil."""
        existing = {n.lower() for n in await self._all_names()}
        today = datetime.date.today()
        inserted: list[str] = []
        for name, kind in sources.items():
            if name.lower() in existing or kind not in DEFAULT_GRADES:
                continue
            grade, code = DEFAULT_GRADES[kind]
            self.session.add(
                SourceReliabilityEntry(
                    source_name=name,
                    analyst_name="system",
                    reliability_grade=grade,
                    credibility_code=code,
                    admiralty_code=f"{grade}{code}",
                    notes="",
                    added_date=today,
                    last_updated=today,
                    origin="default",
                )
            )
            existing.add(name.lower())
            inserted.append(name)
        await self.session.flush()
        return inserted

    async def _all_names(self) -> list[str]:
        result = await self.session.execute(select(SourceReliabilityEntry.source_name))
        return list(result.scalars().all())

    async def get_all_ratings(self) -> dict[str, SourceReliabilityEntry]:
        """`{source_name.lower(): entry}` -- preload semua entry buat
        lookup cepat (`confidence.recompute_all_confidence`, Fase 7.4 Grup
        D), port optimasi `ratings = {r["source_name"].lower(): r ...}`
        legacy biar gak N+1 query per artikel."""
        result = await self.session.execute(select(SourceReliabilityEntry))
        return {e.source_name.lower(): e for e in result.scalars().all()}

    async def list_low_reliability_source_names(self) -> set[str]:
        """Nama source grade D/E/F, lowercase -- port `_fetch_low_
        reliability_sources()` (`cluster_service.py`, Fase 7.4 Grup A),
        dipakai `exclude_low_reliability` pas clustering (cegah source
        gak reliable jadi anchor cluster baru)."""
        result = await self.session.execute(
            select(SourceReliabilityEntry.source_name).where(
                SourceReliabilityEntry.reliability_grade.in_(["D", "E", "F"])
            )
        )
        return {n.lower() for n in result.scalars().all() if n}

    async def get_by_id(self, entry_id: int) -> SourceReliabilityEntry | None:
        result = await self.session.execute(
            select(SourceReliabilityEntry).where(SourceReliabilityEntry.id == entry_id)
        )
        return result.scalar_one_or_none()

    async def add_entry(
        self,
        *,
        source_name: str,
        analyst_name: str,
        reliability_grade: str,
        credibility_code: str,
        notes: str,
    ) -> tuple[SourceReliabilityEntry | None, str]:
        """`(None, "duplicate")` kalau nama sumber udah ada
        (case-insensitive) -- port perilaku lama, bukan raise."""
        if await self.get_by_name_ci(source_name) is not None:
            return None, "duplicate"
        today = datetime.date.today()
        entry = SourceReliabilityEntry(
            source_name=source_name,
            analyst_name=analyst_name,
            reliability_grade=reliability_grade.upper(),
            credibility_code=credibility_code,
            admiralty_code=f"{reliability_grade.upper()}{credibility_code}",
            notes=notes,
            added_date=today,
            last_updated=today,
            origin="analyst",
        )
        self.session.add(entry)
        await self.session.flush()
        return entry, "ok"

    async def update_entry(
        self,
        entry_id: int,
        *,
        analyst_name: str,
        reliability_grade: str,
        credibility_code: str,
        notes: str,
    ) -> bool:
        entry = await self.get_by_id(entry_id)
        if entry is None:
            return False
        entry.analyst_name = analyst_name
        entry.reliability_grade = reliability_grade.upper()
        entry.credibility_code = credibility_code
        entry.admiralty_code = f"{reliability_grade.upper()}{credibility_code}"
        entry.notes = notes
        entry.origin = "analyst"
        entry.last_updated = datetime.date.today()
        await self.session.flush()
        return True

    async def delete_entry(self, entry_id: int) -> bool:
        entry = await self.get_by_id(entry_id)
        if entry is None:
            return False
        await self.session.delete(entry)
        await self.session.flush()
        return True

    async def get_stats(self) -> dict[str, object]:
        total = (
            await self.session.execute(select(func.count()).select_from(SourceReliabilityEntry))
        ).scalar_one()
        by_grade_result = await self.session.execute(
            select(SourceReliabilityEntry.reliability_grade, func.count())
            .group_by(SourceReliabilityEntry.reliability_grade)
            .order_by(SourceReliabilityEntry.reliability_grade)
        )
        return {
            "total": total,
            "by_grade": [{"grade": g, "count": c} for g, c in by_grade_result.all()],
        }

    async def get_ungraded_sources(self) -> list[str]:
        """Port `/ungraded-sources` -- nama `Article.source` distinct yang
        BELUM ada entry grading-nya (case-insensitive)."""
        all_sources_result = await self.session.execute(
            select(Article.source).where(Article.source != "").distinct()
        )
        graded_result = await self.session.execute(select(SourceReliabilityEntry.source_name))
        graded_lower = {s.lower() for s in graded_result.scalars().all()}
        all_sources = [s for s in all_sources_result.scalars().all() if s]
        return sorted(s for s in all_sources if s.lower() not in graded_lower)
