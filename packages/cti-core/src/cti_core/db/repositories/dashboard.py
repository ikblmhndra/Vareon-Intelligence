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

from sqlalchemy import Date, Integer, Select, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.db.models.article import (
    Article,
    ArticleCountry,
    ArticleIndustry,
    ArticleThreatActor,
    ArticleTTP,
)
from cti_core.db.models.cve import CveTicket, CveTracker
from cti_core.db.models.ioc import IOC
from cti_core.db.models.ta import TAWatchlistEntry
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


_NOT_AFFECTED_RISK = "No Risk (Not Affected)"
_RESOLVED_STATUSES = (
    "risk accepted",
    "resolved",
    "closed",
    "completed",
    "not affected",
    "not applicable",
)
"""Status ticket yang bukan beban kerja lagi; cermin `_STATUS_ALIASES` di
`cti_api.services.cve_dashboard` (bucket `risk_accepted`, `completed`, `not_affected`)."""


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

    async def unique_industry_count(
        self, *, exclude_industry: str | None = None, **filters: Any
    ) -> int:
        stmt = _apply_article_filters(
            select(func.count(func.distinct(ArticleIndustry.industry)))
            .select_from(Article)
            .join(ArticleIndustry),
            **filters,
        )
        if exclude_industry is not None:
            stmt = stmt.where(ArticleIndustry.industry != exclude_industry)
        return int((await self.session.execute(stmt)).scalar_one())

    async def distinct_day_count(self, **filters: Any) -> int:
        """Jumlah HARI (`posted_on`) yang punya minimal satu artikel. Dipakai buat menilai apakah
        periode pembanding punya data yang layak: 3 artikel nyasar di jendela 30 hari = 3 hari,
        bukan "ada data"."""
        stmt = _apply_article_filters(
            select(func.count(func.distinct(Article.posted_on))).where(
                Article.posted_on.is_not(None)
            ),
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

    async def article_timeline(self, **filters: Any) -> list[tuple[datetime.date, int, int]]:
        """(hari, jumlah artikel, jumlah insiden terkonfirmasi) per hari; kartu "Artikel dari
        waktu ke waktu" menggambar dua seri."""
        stmt = (
            _apply_article_filters(
                select(
                    Article.posted_on,
                    func.count(),
                    func.count().filter(Article.confirmed_incident.is_(True)),
                ).where(Article.posted_on.is_not(None)),
                **filters,
            )
            .group_by(Article.posted_on)
            .order_by(Article.posted_on)
            .limit(365)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(d, cnt, inc) for d, cnt, inc in rows]

    async def coverage_counts(self, **filters: Any) -> dict[str, int]:
        """Jumlah ARTIKEL (bukan baris) yang punya minimal satu negara / threat
        actor / TTP. Penyebut buat chart dashboard: di prod cuma ~16% / 7% /
        46% artikel yang punya datanya, jadi tanpa angka ini chart kelihatan
        lebih penuh daripada basis datanya."""
        out: dict[str, int] = {}
        for key, model in (
            ("with_country", ArticleCountry),
            ("with_actor", ArticleThreatActor),
            ("with_ttp", ArticleTTP),
        ):
            stmt = _apply_article_filters(
                select(func.count(func.distinct(Article.id))).select_from(Article).join(model),
                **filters,
            )
            out[key] = int((await self.session.execute(stmt)).scalar_one())
        return out

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
        posted_on_end: datetime.date | None = None,
        countries: Sequence[str] | None = None,
        news_types: Sequence[str] | None = None,
        search: str | None = None,
    ) -> list[tuple[datetime.date, str, int]]:
        """`dimension`: "threat_actor" | "country" | "industry" | "ttp". Port
        `by_actor`/`by_country`/`by_industry` facet `spike_service.py`.
        `exclude_news_types`/`confirmed_only` cuma kepake pas dipanggil
        dari `exec_dashboard_v2` (`industry_spikes`, ikut filter
        `incident_only`/`confirmed_only` dashboard) -- `/api/spikes`
        polos manggil tanpa ini, sama kayak lama.

        "ttp" mengembalikan entity `"<ttp_id>|<nama kanonik>"` (digabung di SQL,
        dipecah lagi oleh `cti_api.services.trending`). Group by `ttp_id` SAJA
        dengan nama dari `canonical_ttp_name()` -- group by `ttp_name` juga
        memecah satu technique jadi beberapa baris kalau ejaan LLM beda
        (QA BUG-04). `posted_on_end`
        EKSKLUSIF (sama kayak `_apply_article_filters`). `countries`,
        `news_types` dan `search` (ILIKE judul) baru dipasang kalau diisi,
        jadi caller lama (`/api/spikes`, `exec_dashboard`) tidak berubah."""
        # Negara: role apa pun (lihat `_country_role`) -- `count(DISTINCT
        # article.id)` biar negara yang sama di dua role gak kehitung dobel.
        # Buat TA/industri efeknya nol (unik per artikel di level constraint).
        # `key` = kolom GROUP BY/filter kosong, `col` = nilai yang dikembalikan
        # (beda cuma buat "ttp": nama kanonik itu agregat, jadi tidak boleh di WHERE).
        model, key, col = {
            "threat_actor": (
                ArticleThreatActor,
                ArticleThreatActor.threat_actor,
                ArticleThreatActor.threat_actor,
            ),
            "country": (ArticleCountry, ArticleCountry.country_code, ArticleCountry.country_code),
            "industry": (ArticleIndustry, ArticleIndustry.industry, ArticleIndustry.industry),
            "ttp": (
                ArticleTTP,
                ArticleTTP.ttp_id,
                func.concat(ArticleTTP.ttp_id, "|", canonical_ttp_name()),
            ),
        }[dimension]
        stmt = _apply_article_filters(
            select(Article.posted_on, col, func.count(func.distinct(Article.id)))
            .select_from(Article)
            .join(model)
            .where(key.is_not(None), key != ""),
            posted_on_start=posted_on_start,
            posted_on_end=posted_on_end,
            exclude_news_types=exclude_news_types,
            confirmed_only=confirmed_only,
        )
        if countries:
            # Negara role apa pun; subquery (bukan join) biar hitungan
            # `count(DISTINCT article.id)` tidak ikut berlipat.
            stmt = stmt.where(
                Article.id.in_(
                    select(ArticleCountry.article_id).where(
                        ArticleCountry.country_code.in_(countries)
                    )
                )
            )
        if news_types:
            stmt = stmt.where(Article.news_type.in_(news_types))
        if search:
            stmt = stmt.where(Article.title.ilike(f"%{search}%"))
        stmt = stmt.group_by(Article.posted_on, key)
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

    async def cve_kpi_counts(self) -> dict[str, int]:
        """Total UTUH untuk dua KPI Exec: CVE berseverity CRITICAL dan CVE yang ditandai KEV
        (`cisa_kev`, semua severity -- arti "known exploited", bukan subset critical).

        Cakupannya sama dengan `cve_tech_severity_breakdown`: lintas client tanpa filter
        `client_id`, dan baris yang ditandai FP oleh clientnya sendiri tidak dihitung. Bedanya,
        tanpa `limit`: kartu KPI dulu menjumlah kolom `critical` dari tabel exposure yang hanya
        10 tech teratas, sehingga mengecil bila lebih dari 10 tech punya CVE critical."""
        upper_sev = func.upper(CveTracker.cve_severity)
        stmt = select(
            func.sum(cast(upper_sev == "CRITICAL", Integer)),
            func.sum(cast(CveTracker.cisa_kev, Integer)),
        ).where(~is_false_positive_row())
        critical, kev = (await self.session.execute(stmt)).one()
        return {"critical": critical or 0, "kev": kev or 0}

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

    # ── Overview dashboard (peta, perhatian, eksposur CVE) ─────────────────

    async def incident_country_profile(
        self, *, posted_on_start: datetime.date | None
    ) -> list[tuple[str, int, str | None, str | None]]:
        """Profil per negara untuk peta dashboard: `(country_code, jumlah artikel insiden
        terkonfirmasi, aktor teratas atau None, industri teratas non-"General" atau None)`.
        Negara = role APA PUN di `article_countries` (spec 4.4); jumlah memakai
        `count(DISTINCT article.id)` supaya artikel dengan dua role untuk negara yang sama
        dihitung sekali. Aktor/industri teratas memakai himpunan artikel yang sama.
        Aktor/industri dipilih terbanyak, seri sama diurutkan nama biar deterministik.
        Urutan hasil: jumlah desc, lalu kode negara."""
        counts = _apply_article_filters(
            select(ArticleCountry.country_code, func.count(func.distinct(Article.id)))
            .select_from(Article)
            .join(ArticleCountry),
            posted_on_start=posted_on_start,
            posted_on_end=None,
            confirmed_only=True,
        ).group_by(ArticleCountry.country_code)
        count_rows = (await self.session.execute(counts)).all()
        if not count_rows:
            return []

        async def _top_by_country(label: Any, join_model: Any, *extra: Any) -> dict[str, str]:
            n = func.count(func.distinct(Article.id))
            stmt = _apply_article_filters(
                select(ArticleCountry.country_code, label, n)
                .select_from(Article)
                .join(ArticleCountry)
                .join(join_model, join_model.article_id == Article.id)
                .where(*extra),
                posted_on_start=posted_on_start,
                posted_on_end=None,
                confirmed_only=True,
            ).group_by(ArticleCountry.country_code, label)
            best: dict[str, tuple[int, str]] = {}
            for code, name, cnt in (await self.session.execute(stmt)).all():
                cur = best.get(code)
                if cur is None or cnt > cur[0] or (cnt == cur[0] and name < cur[1]):
                    best[code] = (cnt, name)
            return {code: name for code, (_, name) in best.items()}

        actors = await _top_by_country(ArticleThreatActor.threat_actor, ArticleThreatActor)
        industries = await _top_by_country(
            ArticleIndustry.industry,
            ArticleIndustry,
            func.lower(ArticleIndustry.industry) != "general",
        )
        rows = [
            (code, int(cnt), actors.get(code), industries.get(code)) for code, cnt in count_rows
        ]
        rows.sort(key=lambda r: (-r[1], r[0]))
        return rows

    async def watchlist_hit_count(
        self, *, client_id: str, posted_on_start: datetime.date | None
    ) -> int:
        """Jumlah artikel DISTINCT yang menyebut nama dari `ta_watchlist` milik `client_id`
        (cocok case-insensitive ke `article_threat_actors`). Watchlist client lain tidak ikut."""
        stmt = _apply_article_filters(
            select(func.count(func.distinct(Article.id)))
            .select_from(Article)
            .join(ArticleThreatActor, ArticleThreatActor.article_id == Article.id)
            .join(
                TAWatchlistEntry,
                and_(
                    func.lower(TAWatchlistEntry.name)
                    == func.lower(ArticleThreatActor.threat_actor),
                    TAWatchlistEntry.client_id == client_id,
                ),
            ),
            posted_on_start=posted_on_start,
            posted_on_end=None,
        )
        return int((await self.session.execute(stmt)).scalar_one())

    @staticmethod
    def _open_cve_stmt(
        stmt: Select[tuple[Any, ...]],
        *,
        client_id: str,
        tech: Sequence[str] | None,
        exclude_cve_ids: Sequence[str] | None,
    ) -> Select[tuple[Any, ...]]:
        """CVE client yang masih terbuka = definisi backlog halaman CVE Dashboard
        (`cti_api.services.cve_dashboard.BACKLOG_BUCKETS`): belum punya ticket, atau ticket-nya
        tanpa `closure_date` DAN bukan Not Affected / Risk Accepted / Completed. Dulu ticket
        "No Risk (Not Affected)" yang belum ditutup ikut terhitung, jadi Dashboard bilang 32
        critical terbuka sementara CVE Dashboard bilang 30 (audit UI U6/U20). `tech=None` = tanpa
        filter tech, `tech=[]` = tidak ada yang cocok (kontrak sama dengan `_active_tech_names` /
        `AsyncCveTrackerRepo.get_stats`)."""
        status = func.lower(func.trim(func.coalesce(CveTicket.remediation_status, "")))
        stmt = stmt.where(CveTracker.client_id == client_id).where(
            or_(
                CveTicket.id.is_(None),
                and_(
                    CveTicket.closure_date.is_(None),
                    func.coalesce(CveTicket.risk_acceptance, "") != _NOT_AFFECTED_RISK,
                    status.notin_(_RESOLVED_STATUSES),
                ),
            )
        )
        if tech is not None:
            stmt = stmt.where(CveTracker.tech.in_(tech))
        if exclude_cve_ids:
            stmt = stmt.where(CveTracker.cve_id.notin_(exclude_cve_ids))
        return stmt

    @staticmethod
    def _tracker_ticket_join() -> Any:
        return and_(
            CveTicket.cve_id == CveTracker.cve_id, CveTicket.client_id == CveTracker.client_id
        )

    async def cve_exposure(
        self,
        *,
        client_id: str,
        tech: Sequence[str] | None,
        exclude_cve_ids: Sequence[str] | None,
        limit: int = 3,
    ) -> list[tuple[CveTracker, CveTicket | None]]:
        """CVE terbuka teratas beserta ticket-nya (bila ada): KEV dulu, lalu skor CVSS
        tertinggi (NULL terakhir), `cve_id` sebagai pemutus seri."""
        stmt = self._open_cve_stmt(
            select(CveTracker, CveTicket).outerjoin(CveTicket, self._tracker_ticket_join()),
            client_id=client_id,
            tech=tech,
            exclude_cve_ids=exclude_cve_ids,
        )
        stmt = stmt.order_by(
            CveTracker.cisa_kev.desc(), CveTracker.cve_score.desc().nulls_last(), CveTracker.cve_id
        ).limit(limit)
        return [(c, t) for c, t in (await self.session.execute(stmt)).all()]

    async def cve_exposure_counts(
        self,
        *,
        client_id: str,
        tech: Sequence[str] | None,
        exclude_cve_ids: Sequence[str] | None,
    ) -> dict[str, int]:
        """Hitungan CVE terbuka: `open_critical` (`cve_score >= 9.0`, bucket yang sama dengan
        `AsyncCveTrackerRepo.get_stats` supaya angka dashboard = angka halaman CVE),
        `open_kev` (cisa_kev) dan `kev_without_ticket` (KEV yang belum punya ticket sama sekali)."""
        crit = func.sum(cast(CveTracker.cve_score >= 9.0, Integer))
        kev = func.sum(cast(CveTracker.cisa_kev, Integer))
        kev_no_ticket = func.sum(cast(and_(CveTracker.cisa_kev, CveTicket.id.is_(None)), Integer))
        stmt = self._open_cve_stmt(
            select(crit, kev, kev_no_ticket)
            .select_from(CveTracker)
            .outerjoin(CveTicket, self._tracker_ticket_join()),
            client_id=client_id,
            tech=tech,
            exclude_cve_ids=exclude_cve_ids,
        )
        c, k, n = (await self.session.execute(stmt)).one()
        return {
            "open_critical": int(c or 0),
            "open_kev": int(k or 0),
            "kev_without_ticket": int(n or 0),
        }

    async def tickets_closed(
        self, *, client_id: str, since: datetime.date | None
    ) -> tuple[int, float | None]:
        """`(jumlah ticket dengan closure_date >= since, rata-rata hari closure_date -
        created_at::date dibulatkan 1 desimal)`. `since=None` = semua ticket tertutup.
        Rata-rata None bila tidak ada ticket."""
        days = CveTicket.closure_date - cast(CveTicket.created_at, Date)
        stmt = select(func.count(CveTicket.id), func.avg(days)).where(
            CveTicket.client_id == client_id, CveTicket.closure_date.is_not(None)
        )
        if since is not None:
            stmt = stmt.where(CveTicket.closure_date >= since)
        n, avg = (await self.session.execute(stmt)).one()
        return int(n), (round(float(avg), 1) if avg is not None else None)

    # ── IOC (global, gak ada client_id -- lihat docstring modul) ────────────

    async def pending_fp_queue(self, *, limit: int = 20) -> list[IOC]:
        stmt = (
            select(IOC)
            .where(IOC.confidence_score >= 40, IOC.confidence_score < 75)
            .order_by(IOC.last_seen_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def pending_fp_count(self) -> int:
        """Total antrean FP (kondisi sama dengan `pending_fp_queue`, tanpa `limit`): panel cuma
        menampilkan 20 baris teratas, jadi tanpa angka ini kedalaman antrean tidak kelihatan."""
        stmt = (
            select(func.count())
            .select_from(IOC)
            .where(IOC.confidence_score >= 40, IOC.confidence_score < 75)
        )
        return int((await self.session.execute(stmt)).scalar_one())
