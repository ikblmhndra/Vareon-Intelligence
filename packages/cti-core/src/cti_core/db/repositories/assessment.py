"""Muat fakta artikel dari DB lalu tulis hasil `assess()` (P6 spec 2 dan 3.1).

Satu-satunya tempat yang mengubah state DB jadi `ArticleFacts` dan menulis kolom penilaian
(`reliability_grade`, `credibility`, `confidence_score`, `priority_score`, `score_reasons`).
Pemanggilnya dua dunia: persist enrichment dan task story refresh (sync, psycopg, worker) serta
recompute dan API (async, asyncpg). Supaya skor tidak beda antar jalur, query fakta dibangun
SEKALI (`facts_stmt`) sebagai `Select` Core biasa tanpa fitur khusus driver, dan nilai UPDATE
juga dibangun satu helper (`_update_params`); varian sync/async cuma beda `await`.

Semua fakta diambil dalam SATU statement untuk sekumpulan id (subquery berkorelasi + satu
LATERAL untuk baris reliabilitas sumber), bukan query per artikel: recompute jalan per halaman
500 artikel. Pemanggil yang menjamin batas 500 id itu."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import RowMapping, Select, case, false, func, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.confidence import BONUS_TTP_SOURCES, ArticleFacts, Assessment, assess
from cti_core.db.models.article import Article, ArticleThreatActor, ArticleTTP
from cti_core.db.models.article_cve import ArticleCve
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.indicator import Indicator, IndicatorSource
from cti_core.db.models.source_reliability import SourceReliabilityEntry
from cti_core.db.models.story import Story
from cti_core.db.repositories.cve import is_false_positive_row


def facts_stmt(article_ids: Sequence[int]) -> Select[Any]:
    """Satu baris per artikel yang ada di `article_ids` (id yang tidak ada tidak muncul).

    Baris sumber dipilih seperti `source_reliability._by_name_ci_stmt` (nama case-insensitive,
    baris analis dulu lalu `id` terkecil) tapi lewat LATERAL supaya tetap satu query. KEV/PoC
    mengikuti `AsyncCveTrackerRepo.exploit_flags`: hanya CVE yang di-track, baris yang ditandai
    FP oleh client pemiliknya diabaikan, cukup satu baris bertanda."""
    sr = SourceReliabilityEntry
    sr_pick = (
        select(sr.reliability_grade, sr.content_kind)
        .where(func.lower(sr.source_name) == func.lower(Article.source))
        .order_by(case((sr.origin == "analyst", 0), else_=1), sr.id)
        .limit(1)
        .lateral("sr_pick")
    )

    has_cve = select(ArticleCve.article_id).where(ArticleCve.article_id == Article.id).exists()
    has_ioc = (
        select(IndicatorSource.id)
        .join(Indicator, Indicator.id == IndicatorSource.indicator_id)
        .where(IndicatorSource.article_id == Article.id, Indicator.usable)
        .exists()
    )
    has_actor = (
        select(ArticleThreatActor.id).where(ArticleThreatActor.article_id == Article.id).exists()
    )

    def _ttp_count(sources: Sequence[str]) -> Any:
        return (
            select(func.count())
            .select_from(ArticleTTP)
            .where(ArticleTTP.article_id == Article.id, ArticleTTP.source.in_(sources))
            .scalar_subquery()
        )

    def _cve_flag(column: Any) -> Any:
        return (
            select(func.coalesce(func.bool_or(column), false()))
            .select_from(ArticleCve)
            .join(CveTracker, func.upper(CveTracker.cve_id) == func.upper(ArticleCve.cve_id))
            .where(ArticleCve.article_id == Article.id, ~is_false_positive_row())
            .scalar_subquery()
        )

    return (
        select(
            Article.id.label("id"),
            sr_pick.c.reliability_grade.label("reliability_grade"),
            sr_pick.c.content_kind.label("content_kind"),
            func.greatest(func.coalesce(Story.source_count, 1), 1).label("story_source_count"),
            has_cve.label("has_cve"),
            has_ioc.label("has_ioc"),
            _ttp_count(["explicit"]).label("explicit_ttp_count"),
            _ttp_count(sorted(BONUS_TTP_SOURCES)).label("bonus_ttp_count"),
            has_actor.label("has_actor"),
            Article.confirmed_incident.label("confirmed_incident"),
            _cve_flag(CveTracker.cisa_kev).label("kev"),
            _cve_flag(CveTracker.poc_available).label("poc"),
            Article.overrides.label("overrides"),
        )
        .select_from(Article)
        .outerjoin(sr_pick, true())
        .outerjoin(Story, Story.id == Article.story_id)
        .where(Article.id.in_(list(article_ids)))
        .order_by(Article.id)
    )


def _override_int(overrides: Mapping[str, Any] | None, key: str, lo: int, hi: int) -> int | None:
    """Nilai override yang bukan int (string, float, null, bool) atau di luar `lo..hi` dianggap
    TIDAK ada override, bukan error: satu `overrides` JSONB yang rusak tidak boleh menggagalkan
    batch 500 artikel (credibility 0/7 melanggar ck_articles_credibility_range).
    `bool` subclass `int` di Python, jadi dikecualikan eksplisit."""
    value = (overrides or {}).get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        return None
    return value


def facts_from_row(row: RowMapping) -> ArticleFacts:
    """Baris `facts_stmt` (`.mappings()`) -> `ArticleFacts`. Override analis dibaca sebagai int."""
    overrides = row["overrides"]
    return ArticleFacts(
        reliability_grade=row["reliability_grade"],
        content_kind=row["content_kind"],
        story_source_count=int(row["story_source_count"]),
        has_cve=bool(row["has_cve"]),
        has_ioc=bool(row["has_ioc"]),
        explicit_ttp_count=int(row["explicit_ttp_count"]),
        bonus_ttp_count=int(row["bonus_ttp_count"]),
        has_actor=bool(row["has_actor"]),
        confirmed_incident=bool(row["confirmed_incident"]),
        kev=bool(row["kev"]),
        poc=bool(row["poc"]),
        credibility_override=_override_int(overrides, "credibility", 1, 6),
        confidence_override=_override_int(overrides, "confidence_score", 0, 100),
    )


def _assess_rows(rows: Sequence[RowMapping]) -> dict[int, Assessment]:
    return {int(row["id"]): assess(facts_from_row(row)) for row in rows}


def _update_params(assessments: Mapping[int, Assessment]) -> list[dict[str, Any]]:
    """Parameter ORM bulk UPDATE by primary key (executemany, satu statement per panggilan).

    Catatan: bulk UPDATE ini tidak menyegarkan objek `Article` yang sudah ada di identity map
    sesi; pemanggil yang masih memegang objeknya harus `refresh` kalau butuh nilai baru."""
    return [
        {
            "id": article_id,
            "reliability_grade": a.reliability_grade,
            "credibility": a.credibility,
            "confidence_score": a.confidence_score,
            "priority_score": a.priority_score,
            "score_reasons": a.reasons,
        }
        for article_id, a in assessments.items()
    ]


def apply_assessments(session: Session, article_ids: Sequence[int]) -> dict[int, Assessment]:
    """Nilai ulang dan tulis kolom penilaian `article_ids` (maks 500). Flush saja, tanpa commit:
    transaksi milik pemanggil. Kembalian: id artikel -> `Assessment`; id yang tidak ada
    dilewati.

    Catatan: ditulis lewat ORM bulk UPDATE yang TIDAK menyegarkan objek `Article` yang sudah ada
    di identity map sesi; pemanggil yang masih memegang objeknya harus `session.refresh(...)`
    (atau select ulang) sebelum membaca kolom penilaian."""
    if not article_ids:
        return {}
    rows = session.execute(facts_stmt(article_ids)).mappings().all()
    assessments = _assess_rows(rows)
    if assessments:
        session.execute(update(Article), _update_params(assessments))
        session.flush()
    return assessments


async def apply_assessments_async(
    session: AsyncSession, article_ids: Sequence[int]
) -> dict[int, Assessment]:
    """Versi async `apply_assessments` (API/recompute); statement dan nilai UPDATE sama persis.

    Catatan: ditulis lewat ORM bulk UPDATE yang TIDAK menyegarkan objek `Article` yang sudah ada
    di identity map sesi; pemanggil yang masih memegang objeknya harus `await session.refresh(...)`
    (atau select ulang) sebelum membaca kolom penilaian."""
    if not article_ids:
        return {}
    rows = (await session.execute(facts_stmt(article_ids))).mappings().all()
    assessments = _assess_rows(rows)
    if assessments:
        await session.execute(update(Article), _update_params(assessments))
        await session.flush()
    return assessments
