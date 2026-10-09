"""Query agregasi lintas `articles`/`cve_tracker`/`iocs`, dipakai bareng
`intelligence`/`exec_dashboard`/`recap` (Fase 7.3, Bagian 5). Port dari
`exec_dashboard_service.py`/`exec_dashboard_v2_service.py`/
`spike_service.py`/`risk_matrix_service.py` (bagian query Mongo
aggregation-nya doang -- kalkulasi Python murni tetap di
`cti_api.services.*`, sama pembagian tanggung jawab kayak router lain).

Bucket bulanan pakai `func.to_char(Article.posted_on, 'YYYY-MM')`, ganti
`{"$substr": ["$posted_on", 0, 7]}` Mongo lama. **Expression `to_char(...)`
HARUS diassign ke variabel dan dipakai ULANG objek yang sama di SELECT
dan GROUP BY** -- dua panggilan `func.to_char(...)` terpisah bikin
SQLAlchemy generate dua bind parameter beda (`$1`/`$4`) walau nilainya
sama, Postgres nolak ("must appear in GROUP BY clause"). Bug real yang
udah ketemu di `AsyncTARepo.get_timeline()` (Fase 7.3 Bagian 3), sama
pola persis di sini.

`IOC` gak punya kolom `client_id` (tabel global, bukan multi-tenant --
lihat `models/ioc.py`) -- `pending_fp_queue()` gak nge-scope client sama
sekali, beda dari `cve_tech_severity_breakdown()` yang `CveTracker`-nya
emang multi-tenant."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Date, Integer, Select, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.db.models.article import (
    Article,
    ArticleCountry,
    ArticleIndustry,
    ArticleThreatActor,
    ArticleTTP,
)
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.ioc import IOC
from cti_core.db.repositories.cve import is_false_positive_row
from cti_core.db.repositories.ttp_catalog import canonical_ttp_name


def _apply_article_filters(
    stmt: Select[tuple[Any, ...]],
    *,
    posted_on_start: datetime.date | None,
    posted_on_end: datetime.date | None,
    exclude_news_types: Sequence[str] | None = None,
    confirmed_only: bool = False,
) -> Select[tuple[Any, ...]]:
    if posted_on_start is not None:
        stmt = stmt.where(Article.posted_on >= posted_on_start)
    if posted_on_end is not None:
        stmt = stmt.where(Article.posted_on < posted_on_end)
    if exclude_news_types:
        stmt = stmt.where(
            or_(Article.news_type.is_(None), Article.news_type.not_in(exclude_news_types))
        )
    if confirmed_only:
        stmt = stmt.where(Article.confirmed_incident.is_(True))
    return stmt


def _country_role(stmt: Select[tuple[Any, ...]], role: str | None) -> Select[tuple[Any, ...]]:
    """`role=None` = negara role APA PUN -- padanan `mentioned_countries`
    Mongo lama, yang isinya GABUNGAN regex + victim + actor (lihat
    `cti_core.db.repositories.article._apply_list_filters`). Role
    "mentioned" di skema baru cuma SISA yang gak kepakai victim/actor, jadi
    agregasi "negara yang disebut" yang filter `role == "mentioned"` (bug
    lama, QA BUG-B1) kehilangan mayoritas data. Satu artikel bisa punya
    negara yang SAMA di dua role (victim + actor), makanya hitungan per
    negara pakai `count(DISTINCT article.id)`, bukan `count(*)`."""
    if role is not None:
        stmt = stmt.where(ArticleCountry.role == role)
    return stmt


class AsyncDashboardRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Counts / trends dasar (exec_dashboard v1) ──────────────────────────

    async def count_articles(self, **filters: Any) -> int:
        stmt = _apply_article_filters(select(func.count(Article.id)), **filters)
        return int((await self.session.execute(stmt)).scalar_one())

    async def monthly_industry_counts(self, **filters: Any) -> list[tuple[str, str, int]]:
        month = func.to_char(cast(Article.posted_on, Date), "YYYY-MM")
        stmt = _apply_article_filters(
            select(ArticleIndustry.industry, month, func.count())
            .select_from(Article)
            .join(ArticleIndustry),
            **filters,
        ).group_by(ArticleIndustry.industry, month)
        rows = (await self.session.execute(stmt)).all()
        return [(industry, mo, cnt) for industry, mo, cnt in rows]

    async def monthly_country_counts(
        self, *, role: str | None = None, **filters: Any
    ) -> list[tuple[str, str, int]]:
        month = func.to_char(cast(Article.posted_on, Date), "YYYY-MM")
        stmt = _apply_article_filters(
            _country_role(
                select(ArticleCountry.country_code, month, func.count(func.distinct(Article.id)))
                .select_from(Article)
                .join(ArticleCountry),
                role,
            ),
            **filters,
        ).group_by(ArticleCountry.country_code, month)
        rows = (await self.session.execute(stmt)).all()
        return [(country, mo, cnt) for country, mo, cnt in rows]

    async def top_threat_actors(self, *, limit: int = 10, **filters: Any) -> list[tuple[str, int]]:
        stmt = (
            _apply_article_filters(
                select(ArticleThreatActor.threat_actor, func.count())
                .select_from(Article)
                .join(ArticleThreatActor),
                **filters,
            )
            .group_by(ArticleThreatActor.threat_actor)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(actor, cnt) for actor, cnt in rows]

    async def unique_threat_actor_count(self, **filters: Any) -> int:
        stmt = _apply_article_filters(
            select(func.count(func.distinct(ArticleThreatActor.threat_actor)))
            .select_from(Article)
            .join(ArticleThreatActor),
            **filters,
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def distinct_threat_actors(self, **filters: Any) -> list[str]:
        stmt = _apply_article_filters(
            select(ArticleThreatActor.threat_actor.distinct())
            .select_from(Article)
            .join(ArticleThreatActor),
            **filters,
        )
        result = await self.session.execute(stmt)
        return [r for r in result.scalars().all() if r]

    async def unique_industry_count(self, **filters: Any) -> int:
        stmt = _apply_article_filters(
            select(func.count(func.distinct(ArticleIndustry.industry)))
            .select_from(Article)
            .join(ArticleIndustry),
            **filters,
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def news_type_breakdown(self, **filters: Any) -> list[tuple[str | None, int]]:
        stmt = (
            _apply_article_filters(select(Article.news_type, func.count()), **filters)
            .group_by(Article.news_type)
            .order_by(func.count().desc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [(nt, cnt) for nt, cnt in rows]

    # ── article dashboard (Fase 7.4 Grup D, router `articles` /dashboard) ───
    # Port `article_service._fetch_dashboard_stats()`. Beda dari exec_dashboard
    # di atas: `posted_on_start`/`posted_on_end` DUA-DUANYA opsional (bisa
    # kosong buat "sepanjang waktu"), makanya gak bisa numpang `daily_totals()`
    # (butuh `posted_on_start` wajib, `posted_on_end` diabaikan).
    #
    # `top_countries` SENGAJA gak re-normalize nama negara kayak
    # `normalize_country()` lama (legacy: `mentioned_countries` FREE-TEXT,
    # butuh grouping ulang manual di Python) -- `ArticleCountry.country_code`
    # (Fase 2) UDAH ISO alpha-2 kanonik dari enrichment, masalah yang
    # legacy kerjain di query-time udah beres duluan di data model.

    async def distinct_source_count(self, **filters: Any) -> int:
        stmt = _apply_article_filters(
            select(func.count(func.distinct(Article.source))).where(Article.source != ""),
            **filters,
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def unique_country_count(self, **filters: Any) -> int:
        """Negara role apa pun (lihat `_country_role`)."""
        stmt = _apply_article_filters(
            select(func.count(func.distinct(ArticleCountry.country_code)))
            .select_from(Article)
            .join(ArticleCountry),
            **filters,
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def top_countries(
        self, *, limit: int = 10, role: str | None = None, **filters: Any
    ) -> list[tuple[str, int]]:
        n_articles = func.count(func.distinct(Article.id))
        stmt = (
            _apply_article_filters(
                _country_role(
                    select(ArticleCountry.country_code, n_articles)
                    .select_from(Article)
                    .join(ArticleCountry),
                    role,
                ),
                **filters,
            )
            .group_by(ArticleCountry.country_code)
            .order_by(n_articles.desc(), ArticleCountry.country_code)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(c, cnt) for c, cnt in rows]

    async def top_sources(self, *, limit: int = 10, **filters: Any) -> list[tuple[str, int]]:
        stmt = (
            _apply_article_filters(
                select(Article.source, func.count()).where(Article.source != ""), **filters
            )
            .group_by(Article.source)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(s, cnt) for s, cnt in rows]

    async def top_industries(self, *, limit: int = 10, **filters: Any) -> list[tuple[str, int]]:
        stmt = (
            _apply_article_filters(
                select(ArticleIndustry.industry, func.count())
                .select_from(Article)
                .join(ArticleIndustry),
                **filters,
            )
            .group_by(ArticleIndustry.industry)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(i, cnt) for i, cnt in rows]

    async def article_timeline(self, **filters: Any) -> list[tuple[datetime.date, int]]:
        stmt = (
            _apply_article_filters(
                select(Article.posted_on, func.count()).where(Article.posted_on.is_not(None)),
                **filters,
            )
            .group_by(Article.posted_on)
            .order_by(Article.posted_on)
            .limit(365)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(d, cnt) for d, cnt in rows]

    # ── exec_dashboard v2 -- tier 2/3 ───────────────────────────────────────

    async def ttp_counts(self, *, limit: int = 15, **filters: Any) -> list[tuple[str, str, int]]:
        stmt = (
            _apply_article_filters(
                select(ArticleTTP.ttp_id, canonical_ttp_name(), func.count())
                .select_from(Article)
                .join(ArticleTTP),
                **filters,
            )
            # per ID saja -- lihat `canonical_ttp_name` (QA BUG-04)
            .group_by(ArticleTTP.ttp_id)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(tid, name, cnt) for tid, name, cnt in rows]

    async def monthly_ta_counts(self, **filters: Any) -> list[tuple[str, str, int]]:
        month = func.to_char(cast(Article.posted_on, Date), "YYYY-MM")
        stmt = _apply_article_filters(
            select(ArticleThreatActor.threat_actor, month, func.count())
            .select_from(Article)
            .join(ArticleThreatActor),
            **filters,
        ).group_by(ArticleThreatActor.threat_actor, month)
        rows = (await self.session.execute(stmt)).all()
        return [(actor, mo, cnt) for actor, mo, cnt in rows]

    async def article_industries_for_cooccurrence(self, **filters: Any) -> dict[int, list[str]]:
        """`(article_id -> [industry, ...])` buat artikel yang punya >= 2
        industri -- Python-side, sama kayak `_compute_sector_cooccurrence()`
        lama (proyeksi array per dokumen, bukan pipeline unwind)."""
        stmt = _apply_article_filters(
            select(ArticleIndustry.article_id, ArticleIndustry.industry)
            .select_from(Article)
            .join(ArticleIndustry),
            **filters,
        )
        rows = (await self.session.execute(stmt)).all()
        out: dict[int, list[str]] = {}
        for article_id, industry in rows:
            out.setdefault(article_id, []).append(industry)
        return {aid: inds for aid, inds in out.items() if len(inds) >= 2}

    async def monthly_newstype_counts(self, **filters: Any) -> list[tuple[str | None, str, int]]:
        month = func.to_char(cast(Article.posted_on, Date), "YYYY-MM")
        stmt = _apply_article_filters(
            select(Article.news_type, month, func.count()), **filters
        ).group_by(Article.news_type, month)
        rows = (await self.session.execute(stmt)).all()
        return [(nt, mo, cnt) for nt, mo, cnt in rows]

    async def sector_actor_counts(
        self, *, sectors: Sequence[str], actors: Sequence[str], **filters: Any
    ) -> list[tuple[str, str, int]]:
        if not sectors or not actors:
            return []
        stmt = _apply_article_filters(
            select(ArticleIndustry.industry, ArticleThreatActor.threat_actor, func.count())
            .select_from(Article)
            .join(ArticleIndustry)
            .join(ArticleThreatActor, ArticleThreatActor.article_id == Article.id)
            .where(
                ArticleIndustry.industry.in_(sectors),
                ArticleThreatActor.threat_actor.in_(actors),
            ),
            **filters,
        ).group_by(ArticleIndustry.industry, ArticleThreatActor.threat_actor)
        rows = (await self.session.execute(stmt)).all()
        return [(sector, actor, cnt) for sector, actor, cnt in rows]

    async def ta_confidence_raw(
        self, *, posted_on_start: datetime.date, actors: Sequence[str]
    ) -> list[tuple[str, int, int, int]]:
        """`(actor, total, confirmed_count, has_field_count)` per actor --
        `non_incident_type` count dihitung terpisah lewat `news_type_
        breakdown`-style filter di service layer (biar query ini gak
        perlu tau daftar `NON_INCIDENT_TYPES`, itu urusan service)."""
        if not actors:
            return []
        stmt = (
            select(
                ArticleThreatActor.threat_actor,
                func.count(),
                func.sum(cast(Article.confirmed_incident.is_(True), Integer)),
                func.sum(cast(Article.confirmed_incident.is_not(None), Integer)),
            )
            .select_from(Article)
            .join(ArticleThreatActor)
            .where(
                Article.posted_on >= posted_on_start,
                ArticleThreatActor.threat_actor.in_(actors),
            )
            .group_by(ArticleThreatActor.threat_actor)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(actor, total, conf or 0, has_field or 0) for actor, total, conf, has_field in rows]

    async def non_incident_counts_by_actor(
        self,
        *,
        posted_on_start: datetime.date,
        actors: Sequence[str],
        non_incident_types: Sequence[str],
    ) -> dict[str, int]:
        if not actors or not non_incident_types:
            return {}
        stmt = (
            select(ArticleThreatActor.threat_actor, func.count())
            .select_from(Article)
            .join(ArticleThreatActor)
            .where(
                Article.posted_on >= posted_on_start,
                ArticleThreatActor.threat_actor.in_(actors),
                Article.news_type.in_(non_incident_types),
            )
            .group_by(ArticleThreatActor.threat_actor)
        )
        rows = (await self.session.execute(stmt)).all()
        return {actor: cnt for actor, cnt in rows}

    async def confirmed_incident_rate_raw(self, **filters: Any) -> tuple[int, int]:
        stmt = _apply_article_filters(
            select(
                func.count(), func.sum(cast(Article.confirmed_incident.is_(True), Integer))
            ).where(Article.confirmed_incident.is_not(None)),
            **filters,
        )
        total, confirmed = (await self.session.execute(stmt)).one()
        return total or 0, confirmed or 0

    async def source_counts(self) -> list[tuple[str, int]]:
        stmt = (
            select(Article.source, func.count())
            .group_by(Article.source)
            .order_by(func.count().desc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [(s, c) for s, c in rows]

    # ── spikes / risk matrix (per-hari, bukan per-bulan) ────────────────────

    async def daily_entity_counts(
        self,
        *,
        dimension: str,
        posted_on_start: datetime.date,
        exclude_news_types: Sequence[str] | None = None,
        confirmed_only: bool = False,
    ) -> list[tuple[datetime.date, str, int]]:
        """`dimension`: "threat_actor" | "country" | "industry". Port
        `by_actor`/`by_country`/`by_industry` facet `spike_service.py`.
        `exclude_news_types`/`confirmed_only` cuma kepake pas dipanggil
        dari `exec_dashboard_v2` (`industry_spikes`, ikut filter
        `incident_only`/`confirmed_only` dashboard) -- `/api/spikes`
        polos manggil tanpa ini, sama kayak lama."""
        # Negara: role apa pun (lihat `_country_role`) -- `count(DISTINCT
        # article.id)` biar negara yang sama di dua role gak kehitung dobel.
        # Buat TA/industri efeknya nol (unik per artikel di level constraint).
        model, col = {
            "threat_actor": (ArticleThreatActor, ArticleThreatActor.threat_actor),
            "country": (ArticleCountry, ArticleCountry.country_code),
            "industry": (ArticleIndustry, ArticleIndustry.industry),
        }[dimension]
        stmt = _apply_article_filters(
            select(Article.posted_on, col, func.count(func.distinct(Article.id)))
            .select_from(Article)
            .join(model)
            .where(col.is_not(None), col != ""),
            posted_on_start=posted_on_start,
            posted_on_end=None,
            exclude_news_types=exclude_news_types,
            confirmed_only=confirmed_only,
        )
        stmt = stmt.group_by(Article.posted_on, col)
        rows = (await self.session.execute(stmt)).all()
        return [(d, entity, cnt) for d, entity, cnt in rows]

    async def daily_totals(
        self,
        *,
        posted_on_start: datetime.date,
        exclude_news_types: Sequence[str] | None = None,
        confirmed_only: bool = False,
    ) -> list[tuple[datetime.date, int]]:
        stmt = (
            _apply_article_filters(
                select(Article.posted_on, func.count()),
                posted_on_start=posted_on_start,
                posted_on_end=None,
                exclude_news_types=exclude_news_types,
                confirmed_only=confirmed_only,
            )
            .group_by(Article.posted_on)
            .order_by(Article.posted_on)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(d, c) for d, c in rows]

    async def risk_matrix_rows(self, *, posted_on_start: datetime.date) -> list[dict[str, Any]]:
        """Satu baris per artikel: tanggal + industri/negara/TA/TTP yang
        disebut -- bucketing current-vs-previous + skor dihitung Python-side
        (`cti_api.services.risk_matrix`), sama kayak `_compute_risk_matrix()`
        lama (fetch dokumen mentah, olah manual, bukan pipeline agregasi)."""
        articles_stmt = select(Article.id, Article.posted_on).where(
            Article.posted_on >= posted_on_start
        )
        articles = (await self.session.execute(articles_stmt)).all()
        if not articles:
            return []
        ids = [a.id for a in articles]
        posted_map = {a.id: a.posted_on for a in articles}

        async def _grouped(model: Any, col: Any) -> dict[int, list[str]]:
            stmt = select(model.article_id, col).where(model.article_id.in_(ids))
            rows = (await self.session.execute(stmt)).all()
            out: dict[int, list[str]] = {}
            for aid, val in rows:
                if val and val not in out.get(aid, ()):
                    out.setdefault(aid, []).append(val)
            return out

        industries = await _grouped(ArticleIndustry, ArticleIndustry.industry)
        # Role apa pun (lihat `_country_role`); dedup di `_grouped`.
        countries = await _grouped(ArticleCountry, ArticleCountry.country_code)
        actors = await _grouped(ArticleThreatActor, ArticleThreatActor.threat_actor)
        ttps = await _grouped(ArticleTTP, ArticleTTP.ttp_id)

        return [
            {
                "posted_on": posted_map[aid],
                "industries": industries.get(aid, []),
                "countries": countries.get(aid, []),
                "threat_actors": actors.get(aid, []),
                "ttps": ttps.get(aid, []),
            }
            for aid in ids
        ]

    # ── CVE tech/severity breakdown (unscoped, exec_dashboard) ─────────────

    async def cve_tech_severity_breakdown(
        self, *, limit: int = 10, with_extras: bool = False
    ) -> list[dict[str, Any]]:
        """Lintas client, TANPA filter `client_id` -- port apa adanya dari
        `exec_dashboard_service.py`/`exec_dashboard_v2_service.py` lama
        (dua-duanya query `cve_tracker` polos, gak pernah nge-scope client
        buat widget dashboard eksekutif ini). Baris yang ditandai FP oleh
        clientnya sendiri tidak dihitung (`is_false_positive_row`)."""
        upper_sev = func.upper(CveTracker.cve_severity)
        cols: list[Any] = [
            CveTracker.tech,
            func.count(),
            func.sum(cast(upper_sev == "CRITICAL", Integer)),
            func.sum(cast(upper_sev == "HIGH", Integer)),
            func.sum(cast(upper_sev == "MEDIUM", Integer)),
        ]
        if with_extras:
            cols += [
                func.max(CveTracker.cve_score),
                func.sum(cast(CveTracker.poc_available, Integer)),
            ]
        stmt = select(*cols).where(~is_false_positive_row())
        stmt = stmt.group_by(CveTracker.tech).order_by(cols[2].desc(), cols[1].desc()).limit(limit)
        rows = (await self.session.execute(stmt)).all()
        out = []
        for row in rows:
            entry = {
                "tech": row[0],
                "total": row[1],
                "critical": row[2] or 0,
                "high": row[3] or 0,
                "medium": row[4] or 0,
            }
            if with_extras:
                entry["max_cvss"] = round(row[5] or 0, 1)
                entry["poc_count"] = row[6] or 0
            out.append(entry)
        return out

    async def critical_cves(self, *, client_id: str, limit: int = 20) -> list[CveTracker]:
        """`epss_score >= 0.5` OR `cisa_kev` lama -- cabang EPSS gak ada
        (kolomnya gak ada di skema baru, lihat docstring `routers/cve.py`
        soal `epss_service` yang belum diport), cuma `cisa_kev` yang jalan."""
        stmt = (
            select(CveTracker)
            .where(CveTracker.client_id == client_id, CveTracker.cisa_kev.is_(True))
            .order_by(CveTracker.cve_score.desc().nulls_last())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # ── IOC (global, gak ada client_id -- lihat docstring modul) ────────────

    async def pending_fp_queue(self, *, limit: int = 20) -> list[IOC]:
        stmt = (
            select(IOC)
            .where(IOC.confidence_score >= 40, IOC.confidence_score < 75)
            .order_by(IOC.last_seen_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())
