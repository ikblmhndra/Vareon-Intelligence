"""RansomwareVictimRepo -- upsert ke `ransomware_victims`. Key dedup
`offset_key`, BUKAN url_hash biasa -- sumbernya API snapshot bulanan tanpa
URL stabil per korban (lihat model & RansomwareVictimItem).

`AsyncRansomwareVictimRepo` (Fase 7.3, router `ransomware.py`) BARU --
permukaan BACA doang, tabel ini emang cuma ditulis scraper (lihat docstring
model). Gak ada jalur tulis async di sini SENGAJA."""

from __future__ import annotations

import datetime
from collections.abc import Collection
from typing import Any

import structlog
from sqlalchemy import Date, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.models.article import Article, ArticleThreatActor
from cti_core.db.models.entity import Entity
from cti_core.db.models.ransomware import RansomwareVictim
from cti_core.entity import collapse_ws, relationship_stix_id
from cti_core.entity.mentions import (
    country_mention,
    resolve_mention,
    sector_mention,
    utc_midnight,
)
from cti_core.entity.resolve import resolve

log = structlog.get_logger()

_IDENTITY_FIELDS = frozenset({"id", "offset_key", "created_at"})


_RANSOMWARE_CONFIDENCE = 50

# Kunci unik `uq_relationships_edge` adalah indeks ekspresi (coalesce), jadi ON CONFLICT ditulis
# dengan ekspresinya. Relasi yang sudah ada (termasuk yang di-revoke analis) hanya diperlebar
# rentang first_seen/last_seen-nya; revoke tidak dibatalkan.
_UPSERT_RELATIONSHIP = text(
    """
    INSERT INTO relationships (stix_id, relationship_type, source_entity_id, target_entity_id,
                               confidence, first_seen, last_seen, provenance, created_by)
    VALUES (:stix_id, :rel_type, :src, :dst, :confidence, :seen, :seen, 'ransomware',
            'system:ransomware')
    ON CONFLICT (coalesce(source_entity_id, 0), coalesce(source_indicator_id, 0),
                 relationship_type, target_entity_id)
    DO UPDATE SET first_seen = least(relationships.first_seen, EXCLUDED.first_seen),
                  last_seen = greatest(relationships.last_seen, EXCLUDED.last_seen)
    """
)


def _resolve_named(session: Session, type_: str, name: str, cls: str | None) -> Entity | None:
    """Entitas hidup (tidak suppressed) untuk nama dari sumber ransomware; kosong -> None."""
    if not collapse_ws(name or ""):
        return None
    ent = resolve(session, type_, name, source="ransomware", identity_class=cls)
    return None if ent.suppressed else ent


def _upsert_relationship(
    session: Session, src: Entity, rel_type: str, dst: Entity, seen: datetime.datetime | None
) -> None:
    session.execute(
        _UPSERT_RELATIONSHIP,
        {
            "stix_id": relationship_stix_id(src.stix_id, rel_type, dst.stix_id),
            "rel_type": rel_type,
            "src": src.id,
            "dst": dst.id,
            "confidence": _RANSOMWARE_CONFIDENCE,
            "seen": seen,
        },
    )


class RansomwareVictimRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, *, offset_key: str, **fields: Any) -> RansomwareVictim:
        for k in fields:
            if k in _IDENTITY_FIELDS:
                raise ValueError(f"'{k}' itu field identitas, upsert() gak boleh nimpa ini")

        existing = self.session.execute(
            select(RansomwareVictim).where(RansomwareVictim.offset_key == offset_key)
        ).scalar_one_or_none()

        if existing is None:
            victim = RansomwareVictim(offset_key=offset_key, **fields)
            self.session.add(victim)
            self.session.flush()
            self._link_entities(victim)
            return victim

        for k, v in fields.items():
            setattr(existing, k, v)
        self.session.flush()
        self._link_entities(existing)
        return existing

    def _link_entities(self, victim: RansomwareVictim) -> None:
        """P7c (spec 4.3): grup, korban, negara dan sektor lewat resolver, plus relasi
        `grup targets korban` dan `korban located-at negara` (confidence 50, provenance
        `ransomware`, seen = tanggal `discovered`), sama dengan backfill migrasi. Sektor hanya
        di-resolve (label tak dikenal -> sektor legacy), tanpa relasi -- backfill juga begitu.
        Korban yang resolve ke SEKTOR (identity_class `class`, nama sama dengan sektor) tidak
        ditautkan dan dicatat di log (Ruling 10)."""
        s = self.session
        group = _resolve_named(s, "intrusion-set", victim.group_name, None)
        if victim.industry and (hit := sector_mention(victim.industry, "legacy")):
            resolve_mention(s, hit)
        org = _resolve_named(s, "identity", victim.victim[:300], "organization")
        if org is not None and org.identity_class == "class":
            log.info("ransomware_victim_is_sector", victim=victim.victim, entity_id=org.id)
            return
        country = None
        if victim.country_code and (hit := country_mention(victim.country_code, None, "legacy")):
            country = resolve_mention(s, hit)
        seen = utc_midnight(victim.discovered)
        if group is not None and org is not None:
            _upsert_relationship(s, group, "targets", org, seen)
        if org is not None and country is not None:
            _upsert_relationship(s, org, "located-at", country, seen)

    def get(self, offset_key: str) -> RansomwareVictim | None:
        return self.session.execute(
            select(RansomwareVictim).where(RansomwareVictim.offset_key == offset_key)
        ).scalar_one_or_none()


class AsyncRansomwareVictimRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def weekly_counts(self, *, weeks: int = 8) -> list[tuple[datetime.date, int]]:
        """Korban per minggu (awal minggu = Senin), `weeks` minggu terakhir termasuk minggu
        berjalan, terlama dulu, minggu kosong diisi 0. Tanggal korban =
        `coalesce(discovered, published)`; baris tanpa tanggal tidak dihitung."""
        today = datetime.date.today()
        this_monday = today - datetime.timedelta(days=today.weekday())
        first = this_monday - datetime.timedelta(weeks=weeks - 1)
        when = func.coalesce(RansomwareVictim.discovered, RansomwareVictim.published)
        week = func.date_trunc("week", when)
        stmt = select(cast(week, Date), func.count()).where(when >= first).group_by(week)
        found = {d: int(n) for d, n in (await self.session.execute(stmt)).all()}
        return [
            (d, found.get(d, 0))
            for d in (first + datetime.timedelta(weeks=i) for i in range(weeks))
        ]

    async def summary(
        self,
        *,
        since: datetime.date | None,
        apac_codes: Collection[str],
        client_codes: Collection[str],
    ) -> dict[str, Any]:
        """Ringkasan korban sejak `since` (tanggal = `coalesce(discovered, published)`):
        `total`, `apac`/`client_scope` (kode negara di himpunan masing-masing), `undated`
        (kedua tanggal NULL; TIDAK pernah difilter `since`), `top_groups` (3 teratas,
        seri diurutkan nama) dan `by_country` ({kode: jumlah}, hanya baris berkode)."""
        when = func.coalesce(RansomwareVictim.discovered, RansomwareVictim.published)

        def _scoped(stmt: Any) -> Any:
            return stmt.where(when >= since) if since is not None else stmt.where(when.is_not(None))

        total = (
            await self.session.execute(_scoped(select(func.count(RansomwareVictim.id))))
        ).scalar_one()
        in_apac = (
            await self.session.execute(
                _scoped(
                    select(func.count(RansomwareVictim.id)).where(
                        RansomwareVictim.country_code.in_(list(apac_codes))
                    )
                )
            )
        ).scalar_one()
        in_client = (
            await self.session.execute(
                _scoped(
                    select(func.count(RansomwareVictim.id)).where(
                        RansomwareVictim.country_code.in_(list(client_codes))
                    )
                )
            )
        ).scalar_one()
        undated = (
            await self.session.execute(
                select(func.count(RansomwareVictim.id)).where(
                    RansomwareVictim.discovered.is_(None), RansomwareVictim.published.is_(None)
                )
            )
        ).scalar_one()
        groups = (
            await self.session.execute(
                _scoped(select(RansomwareVictim.group_name, func.count()))
                .group_by(RansomwareVictim.group_name)
                .order_by(func.count().desc(), RansomwareVictim.group_name)
                .limit(3)
            )
        ).all()
        countries = (
            await self.session.execute(
                _scoped(
                    select(RansomwareVictim.country_code, func.count()).where(
                        RansomwareVictim.country_code.is_not(None)
                    )
                ).group_by(RansomwareVictim.country_code)
            )
        ).all()
        return {
            "total": int(total),
            "apac": int(in_apac),
            "client_scope": int(in_client),
            "undated": int(undated),
            "top_groups": [(g, int(n)) for g, n in groups],
            "by_country": {c: int(n) for c, n in countries},
        }

    async def list_by_group_exact(
        self, group_name: str, *, limit: int = 100
    ) -> list[RansomwareVictim]:
        """Exact-match (case-insensitive) `group_name` -- port
        `mermaid_service.build_ransomware_mindmap()` (Fase 7.3, router
        `mindmap`, Bagian 4). BEDA dari `list_filtered(group=...)` yang
        SUBSTRING match (buat UI search box) -- di sini butuh exact match
        persis kayak regex `^...$` Mongo lama."""
        result = await self.session.execute(
            select(RansomwareVictim)
            .where(func.lower(RansomwareVictim.group_name) == group_name.lower())
            .order_by(RansomwareVictim.published.desc().nulls_last(), RansomwareVictim.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_filtered(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        group: str | None = None,
        country: str | None = None,
        industry: str | None = None,
        date_start: datetime.date | None = None,
        date_end: datetime.date | None = None,
    ) -> tuple[list[RansomwareVictim], int]:
        """`date_start`/`date_end` WAJIB `datetime.date`, bukan `str` --
        asyncpg gak auto-cast varchar ke `date` di sisi driver (beda dari
        psycopg2/sync), `Date >= '2026-09-03'` mentah gagal dengan
        `UndefinedFunctionError`. Ketauan lewat test integrasi (bukan
        dugaan) -- router yang parsing string tanggal jadi `datetime.date`
        SEBELUM manggil ini, sama pola kayak `articles`/`cve`."""
        stmt = select(RansomwareVictim)
        if group:
            stmt = stmt.where(RansomwareVictim.group_name.ilike(f"%{group}%"))
        if country:
            stmt = stmt.where(RansomwareVictim.country_code.ilike(f"%{country}%"))
        if industry:
            stmt = stmt.where(RansomwareVictim.industry.ilike(f"%{industry}%"))
        if date_start is not None:
            stmt = stmt.where(RansomwareVictim.published >= date_start)
        if date_end is not None:
            stmt = stmt.where(RansomwareVictim.published <= date_end)

        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        # `id` tiebreaker WAJIB: banyak korban ber-`published` sama (presisi
        # hari), tanpa tiebreaker Postgres bebas ngurutin baris seri beda
        # tiap query -> korban yang sama muncul di page 1 DAN 2, sebagian
        # lain gak pernah tampil (QA BUG-B4: 410 baris, cuma 376 id unik).
        list_stmt = (
            stmt.order_by(
                RansomwareVictim.published.desc().nulls_last(), RansomwareVictim.id.desc()
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(list_stmt)
        return list(result.scalars().all()), total

    async def get_filter_options(self) -> dict[str, list[str]]:
        groups = (
            (await self.session.execute(select(RansomwareVictim.group_name).distinct()))
            .scalars()
            .all()
        )
        countries = (
            (await self.session.execute(select(RansomwareVictim.country_code).distinct()))
            .scalars()
            .all()
        )
        industries = (
            (await self.session.execute(select(RansomwareVictim.industry).distinct()))
            .scalars()
            .all()
        )
        return {
            "groups": sorted(g for g in groups if g),
            "countries": sorted(c for c in countries if c),
            "industries": sorted(i for i in industries if i),
        }

    async def get_related_articles(
        self, *, page: int = 1, page_size: int = 20
    ) -> tuple[list[Article], int]:
        """Port `get_related_articles()` -- artikel yang nyebut nama grup
        ransomware yang tercatat di `ransomware_victims`, baik lewat tag
        `ArticleThreatActor` (exact match) ATAUPUN judul (substring,
        dibatasin 40 grup pertama -- port perilaku lama persis, alasan
        yang sama: batasin ukuran alternation regex/OR)."""
        group_names = (
            (await self.session.execute(select(RansomwareVictim.group_name).distinct()))
            .scalars()
            .all()
        )
        group_names = [g for g in group_names if g]
        if not group_names:
            return [], 0

        top_groups = group_names[:40]
        stmt = (
            select(Article)
            .distinct()
            .outerjoin(ArticleThreatActor)
            .where(
                or_(
                    ArticleThreatActor.threat_actor.in_(group_names),
                    *[Article.title.ilike(f"%{g}%") for g in top_groups],
                )
            )
        )
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        list_stmt = (
            stmt.order_by(Article.posted_on.desc().nulls_last())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(list_stmt)
        return list(result.scalars().unique().all()), total
