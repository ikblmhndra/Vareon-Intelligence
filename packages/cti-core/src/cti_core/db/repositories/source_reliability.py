"""AsyncSourceReliabilityRepo -- CRUD `source_reliability_entries` (Fase
7.3, Bagian 2). Port dari `ScraperNewsWeb/app/services/
source_score_db_service.py`. Grading Admiralty manual analis, global (gak
ada client_id) -- lihat docstring `models/source_reliability.py`."""

from __future__ import annotations

import datetime
from collections.abc import Mapping

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.confidence import DEFAULT_GRADES, SourceStats
from cti_core.db.models.article import Article, ArticleTTP, RejectedArticle
from cti_core.db.models.article_cve import ArticleCve
from cti_core.db.models.indicator import Indicator, IndicatorFeedback, IndicatorSource
from cti_core.db.models.source_reliability import SourceReliabilityEntry
from cti_core.db.models.story import Story

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


def _by_name_ci_stmt(source_name: str) -> Select[tuple[SourceReliabilityEntry]]:
    """Lookup nama case-insensitive yang tidak pernah meledak: keunikan nama hanya dijaga repo
    (bukan constraint DB), jadi baris kembar beda huruf mungkin ada. Lookup ini ada di jalur enrich
    (persist), jadi `scalar_one_or_none` (`MultipleResultsFound`) diganti: baris analis menang,
    lalu `id` terkecil."""
    return (
        select(SourceReliabilityEntry)
        .where(func.lower(SourceReliabilityEntry.source_name) == source_name.lower())
        .order_by(
            case((SourceReliabilityEntry.origin == "analyst", 0), else_=1),
            SourceReliabilityEntry.id,
        )
        .limit(1)
    )


class SourceReliabilityRepo:
    """Versi sync (persist enrichment di worker) -- cuma lookup nama."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_name_ci(self, source_name: str) -> SourceReliabilityEntry | None:
        return self.session.execute(_by_name_ci_stmt(source_name)).scalars().first()


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
        result = await self.session.execute(_by_name_ci_stmt(source_name))
        return result.scalars().first()

    async def ensure_defaults(self, sources: Mapping[str, str]) -> list[str]:
        """`{nama sumber: content_kind}`. Baris `origin='default'` dibuat untuk yang belum ada
        (case-insensitive), grade dari `DEFAULT_GRADES`. Baris yang sudah ada (analis atau default
        lama) TIDAK disentuh grade-nya, tapi `content_kind`-nya selalu disegarkan (P6 spec 3.2).
        Balikin hanya nama yang BARU dimasukkan (memicu recompute). Flush saja, commit di
        pemanggil."""
        rows = (await self.session.execute(select(SourceReliabilityEntry))).scalars().all()
        by_name: dict[str, list[SourceReliabilityEntry]] = {}
        for row in rows:
            by_name.setdefault(row.source_name.lower(), []).append(row)
        today = datetime.date.today()
        inserted: list[str] = []
        for name, kind in sources.items():
            existing = by_name.get(name.lower())
            if existing:
                for row in existing:
                    if row.content_kind != kind:
                        row.content_kind = kind
                continue
            if kind not in DEFAULT_GRADES:
                continue
            grade, code = DEFAULT_GRADES[kind]
            entry = SourceReliabilityEntry(
                source_name=name,
                analyst_name="system",
                reliability_grade=grade,
                credibility_code=code,
                admiralty_code=f"{grade}{code}",
                notes="",
                added_date=today,
                last_updated=today,
                origin="default",
                content_kind=kind,
            )
            self.session.add(entry)
            by_name[name.lower()] = [entry]
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
        credibility_code: str | None,
        notes: str,
    ) -> tuple[SourceReliabilityEntry | None, str]:
        """`(None, "duplicate")` kalau nama sumber udah ada
        (case-insensitive) -- port perilaku lama, bukan raise.

        P6 spec 3.2: kredibilitas tidak lagi diminta form (dihitung per artikel), tapi kolomnya
        tetap diisi untuk pembaca lama; tanpa nilai ditulis `6` ("cannot be judged")."""
        if await self.get_by_name_ci(source_name) is not None:
            return None, "duplicate"
        if credibility_code is None:
            credibility_code = "6"
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
        credibility_code: str | None,
        notes: str,
    ) -> bool:
        """`credibility_code=None` mempertahankan kode tersimpan (P6 spec 3.2: form edit tidak
        lagi menanyakan kredibilitas)."""
        entry = await self.get_by_id(entry_id)
        if entry is None:
            return False
        if credibility_code is not None:
            entry.credibility_code = credibility_code
        entry.analyst_name = analyst_name
        entry.reliability_grade = reliability_grade.upper()
        entry.admiralty_code = f"{entry.reliability_grade}{entry.credibility_code}"
        entry.notes = notes
        entry.origin = "analyst"
        entry.last_updated = datetime.date.today()
        await self.session.flush()
        return True

    async def confirm(
        self, entry_id: int, *, analyst_name: str, reliability_grade: str | None
    ) -> tuple[SourceReliabilityEntry | None, bool]:
        """Analis mengonfirmasi baris (biasanya `origin='default'`) dari antrean review: baris
        jadi milik analis, opsional dengan grade baru (`admiralty_code` ikut, untuk pembaca lama).
        Balikin `(entry, grade_berubah)`; `(None, False)` kalau id tidak ada. Pemanggil yang
        memutuskan recompute dari `grade_berubah`. Flush saja, commit di pemanggil."""
        entry = await self.get_by_id(entry_id)
        if entry is None:
            return None, False
        changed = False
        if reliability_grade is not None and reliability_grade.upper() != entry.reliability_grade:
            entry.reliability_grade = reliability_grade.upper()
            entry.admiralty_code = f"{entry.reliability_grade}{entry.credibility_code}"
            changed = True
        entry.analyst_name = analyst_name
        entry.origin = "analyst"
        entry.last_updated = datetime.date.today()
        await self.session.flush()
        return entry, changed

    async def review_stats(
        self, *, since: datetime.date
    ) -> list[tuple[SourceReliabilityEntry, SourceStats]]:
        """Statistik antrean review (P6 spec 5.3) untuk setiap baris `origin='default'`, urut nama.

        Jendela waktu: artikel lewat `first_seen_at` (waktu ingest, supaya artikel tanpa tanggal
        terbit tetap terhitung) dan penolakan lewat `rejected_at`, keduanya `>= since` (UTC tengah
        malam). Penolakan karena enrichment GAGAL (`failure_kind` terisi atau `reason` berawalan
        `[enrichment_failed]`) tidak dihitung: itu bukan konten di luar topik. Artefak = definisi
        tangga kredibilitas (`repositories.assessment.facts_stmt`): CVE, IOC yang tidak
        di-suppress atau dicabut, atau TTP `explicit`. Story dihitung dari artikel dalam jendela:
        story dengan `source_count > 1`, dan berapa yang `lead_article_id`-nya artikel sumber ini.
        Verdict IOC
        tanpa jendela (feedback jarang) untuk IOC yang PERTAMA dilaporkan sumber ini (baris
        `indicator_sources` paling awal per IOC), supaya FP tidak dibebankan ke sumber yang cuma
        ikut menyebut. Semua nama sumber dicocokkan case-insensitive; agregat per tabel satu
        query."""
        start = datetime.datetime.combine(since, datetime.time.min, tzinfo=datetime.UTC)

        artefact = or_(
            select(ArticleCve.article_id).where(ArticleCve.article_id == Article.id).exists(),
            select(IndicatorSource.id)
            .join(Indicator, Indicator.id == IndicatorSource.indicator_id)
            .where(IndicatorSource.article_id == Article.id, Indicator.usable)
            .exists(),
            select(ArticleTTP.id)
            .where(ArticleTTP.article_id == Article.id, ArticleTTP.source == "explicit")
            .exists(),
        )
        multi = Story.source_count > 1
        art_key = func.lower(Article.source)
        art_rows = await self.session.execute(
            select(
                art_key,
                func.count(Article.id),
                func.count(Article.id).filter(artefact),
                func.count(func.distinct(Story.id)).filter(multi),
                func.count(func.distinct(Story.id)).filter(
                    and_(multi, Story.lead_article_id == Article.id)
                ),
            )
            .select_from(Article)
            .outerjoin(Story, Story.id == Article.story_id)
            .where(Article.first_seen_at >= start)
            .group_by(art_key)
        )
        articles = {k: (int(a), int(f), int(m), int(ld)) for k, a, f, m, ld in art_rows.all()}

        rej_key = func.lower(RejectedArticle.source)
        rej_rows = await self.session.execute(
            select(rej_key, func.count(RejectedArticle.id))
            .where(
                RejectedArticle.rejected_at >= start,
                RejectedArticle.failure_kind.is_(None),
                ~func.coalesce(RejectedArticle.reason, "").startswith("[enrichment_failed]"),
            )
            .group_by(rej_key)
        )
        rejected = {k: int(n) for k, n in rej_rows.all()}

        first_reporter = (
            select(
                IndicatorSource.indicator_id,
                func.lower(IndicatorSource.source_name).label("source"),
            )
            .distinct(IndicatorSource.indicator_id)
            .order_by(
                IndicatorSource.indicator_id, IndicatorSource.first_seen_at, IndicatorSource.id
            )
            .subquery()
        )
        ioc_rows = await self.session.execute(
            select(
                first_reporter.c.source,
                func.count(IndicatorFeedback.id),
                func.count(IndicatorFeedback.id).filter(IndicatorFeedback.verdict == "fp"),
            )
            .join(
                IndicatorFeedback, IndicatorFeedback.indicator_id == first_reporter.c.indicator_id
            )
            .group_by(first_reporter.c.source)
        )
        iocs = {k: (int(v), int(fp)) for k, v, fp in ioc_rows.all()}

        entries = (
            (
                await self.session.execute(
                    select(SourceReliabilityEntry)
                    .where(SourceReliabilityEntry.origin == "default")
                    .order_by(SourceReliabilityEntry.source_name, SourceReliabilityEntry.id)
                )
            )
            .scalars()
            .all()
        )
        out: list[tuple[SourceReliabilityEntry, SourceStats]] = []
        for entry in entries:
            key = entry.source_name.lower()
            n_art, n_artefact, n_multi, n_lead = articles.get(key, (0, 0, 0, 0))
            n_verdicts, n_fp = iocs.get(key, (0, 0))
            out.append(
                (
                    entry,
                    SourceStats(
                        articles=n_art,
                        rejected=rejected.get(key, 0),
                        artefact_articles=n_artefact,
                        multi_source_stories=n_multi,
                        lead_count=n_lead,
                        ioc_verdicts=n_verdicts,
                        ioc_fp=n_fp,
                    ),
                )
            )
        return out

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
