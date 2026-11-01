"""AsyncTARepo (groups/whitelist/watchlist) + AsyncTAProfileRepo (profil
LLM+timeline+dormancy) -- port `ScraperNewsWeb/app/services/ta_service.py`
+ `ta_profile_service.py`. Fase 7.3 (router `ta_groups`, Bagian 3).

Daftar nama TA utama (`ThreatActorGroup`, Fase 5) dipakai bareng
`cti_enrich.stages.score` -- lihat docstring `db/models/ta.py` soal
kenapa gak ada tabel baru terpisah buat itu.

P7c (Task 11): whitelist = entitas aktor `suppressed`, watchlist = `entity_watches`, profil =
`entity_profiles`. Tanda tangan method publik tetap; baris yang dikembalikan kini dataclass
(`WhitelistRow`, `WatchlistRow`, `TAProfileRow`) dengan atribut yang sama seperti baris ORM
lama. Nama dari pengguna di-resolve lewat `entity_aliases` ("apt36" = "Transparent Tribe");
nama yang dikembalikan = `entities.name`."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, case, cast, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.db.models.article import Article
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.entity import Entity, EntityAlias, EntityProfile, EntityWatch
from cti_core.db.models.ransomware import RansomwareVictim
from cti_core.db.models.threat_reference import ThreatActorGroup
from cti_core.db.models.tweet import Tweet
from cti_core.db.repositories.entity import (
    ACTOR,
    entity_ids_matching_column,
    entity_ids_named,
    live_entity,
    mention_rows,
)
from cti_core.entity import alias_norm
from cti_core.entity.merge import set_suppressed_async
from cti_core.entity.resolve import resolve_async

_GROUP_SORT_FIELDS = {
    "name": ThreatActorGroup.name,
    "added_date": ThreatActorGroup.created_at,
    "source": ThreatActorGroup.source,
}
_WATCHLIST_SORT_FIELDS: dict[str, Any] = {"name": Entity.name, "added_date": EntityWatch.created_at}

_TA_ACTOR = "system:ta_groups"
"""Pelaku audit `entity_suppress` bila pemanggil tidak menyebut username."""


@dataclass(frozen=True)
class WhitelistRow:
    """Baris `ta_whitelist` v1: `id` = `entities.id`, `name` huruf kecil, `added_date` lihat
    `_suppressed_at`."""

    id: int
    name: str
    added_date: datetime.datetime


@dataclass(frozen=True)
class WatchlistRow:
    id: int
    name: str
    client_id: str
    created_at: datetime.datetime


@dataclass(frozen=True)
class TAProfileRow:
    id: int
    actor_name: str
    profile: dict[str, Any]
    generated_at: datetime.datetime


def _suppressed_at() -> Any:
    """Waktu stabil entitas masuk whitelist: audit `entity_suppress` (suppressed=true) terbaru
    untuk entitas itu; tanpa audit (suppress dari migrasi/backfill `ta_whitelist`, atau trigger
    view kompatibilitas) = `entities.created_at`. Bukan `updated_at`, yang ikut berubah tiap kali
    entitas disunting (rename, sync ATT&CK, merge)."""
    audit_at = (
        select(func.max(AuditLogEntry.at))
        .where(
            AuditLogEntry.action == "entity_suppress",
            AuditLogEntry.target_id == cast(Entity.id, String),
            AuditLogEntry.detail["suppressed"].as_boolean().is_(True),
        )
        .correlate(Entity)
        .scalar_subquery()
    )
    return func.coalesce(audit_at, Entity.created_at)


async def _find_actor(session: AsyncSession, name: str) -> Entity | None:
    """Aktor (bukan tombstone, suppressed IKUT) yang punya alias `name`; tanpa membuat entitas."""
    norm = alias_norm(name or "")
    if not norm:
        return None
    result = await session.execute(
        select(Entity)
        .join(EntityAlias, EntityAlias.entity_id == Entity.id)
        .where(
            EntityAlias.entity_type == ACTOR,
            EntityAlias.alias_norm == norm,
            Entity.merged_into_id.is_(None),
        )
        .limit(1)
    )
    return result.scalars().first()


class AsyncTARepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_name_ci(self, name: str) -> ThreatActorGroup | None:
        """Fase 7.3 (router `mindmap`, Bagian 4) -- gate "TA ini beneran
        di-track" sebelum generate mindmap, port `build_threat_actor_mindmap()`
        lama (yang nyari `ta_groups` doc dulu sebelum baca profile).

        `.limit(1)` + `.first()` (BUKAN `scalar_one_or_none()`) -- tabel
        gak punya unique constraint di `lower(name)` (cuma di `name`
        mentah), jadi dua baris case-variant (`"APT41"`/`"apt41"`) bisa
        eksis bareng kalau race atau seed manual. `scalar_one_or_none()`
        crash 500 (`MultipleResultsFound`) kalau itu kejadian -- KETEMU
        LIVE Grup G6. Ambil baris pertama (order gak dijamin stabil
        tanpa `order_by`, tapi cukup buat gate baca non-destruktif ini)."""
        result = await self.session.execute(
            select(ThreatActorGroup)
            .where(func.lower(ThreatActorGroup.name) == name.lower())
            .limit(1)
        )
        return result.scalars().first()

    async def list_added_on(self, day: datetime.date) -> list[ThreatActorGroup]:
        """Port `_collect_new_threat_actors()` (`recap_service.py`, Fase
        7.3 router `recap`, Bagian 5) -- filter `added_date == day` lama.
        Tabel ini gak punya kolom `added_date` terpisah (lihat docstring
        model), `created_at::date` (dari `TimestampMixin`) udah nyimpen
        semantik yang sama persis: tanggal grup ini PERTAMA ditambahin."""
        result = await self.session.execute(
            select(ThreatActorGroup).where(func.date(ThreatActorGroup.created_at) == day)
        )
        return list(result.scalars().all())

    async def list_added_between(
        self, start: datetime.date, end: datetime.date, *, limit: int
    ) -> tuple[list[ThreatActorGroup], int]:
        """`(grup yang pertama ditambahkan di [start, end] -- paling awal dulu, maksimal `limit`,
        total sebenarnya)`. Sama dengan `list_added_on` (tanggalnya `created_at::date`), tapi
        dipotong: satu sinkronisasi katalog bisa menambah ratusan grup sekaligus, dan itu tidak
        boleh membengkakkan prompt recap mingguan."""
        added = func.date(ThreatActorGroup.created_at).between(start, end)
        total = (
            await self.session.execute(
                select(func.count()).select_from(ThreatActorGroup).where(added)
            )
        ).scalar_one()
        result = await self.session.execute(
            select(ThreatActorGroup)
            .where(added)
            .order_by(ThreatActorGroup.created_at, ThreatActorGroup.name)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def list_groups(
        self,
        *,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        sort_dir: str = "asc",
    ) -> tuple[list[ThreatActorGroup], int]:
        stmt = select(ThreatActorGroup)
        if search:
            stmt = stmt.where(ThreatActorGroup.name.ilike(f"%{search}%"))
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        order_col = _GROUP_SORT_FIELDS.get(sort_by, ThreatActorGroup.name)
        order = order_col.desc() if sort_dir == "desc" else order_col.asc()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def list_all_names(self) -> list[str]:
        """Semua nama TA group, lowercase -- port `_fetch_ta_names()`
        (`cluster_service.py`, Fase 7.4 Grup A), dipakai deteksi TA
        disebut di judul artikel pas clustering."""
        result = await self.session.execute(select(ThreatActorGroup.name))
        return [n.lower() for n in result.scalars().all() if n]

    async def add_group(self, name: str) -> dict[str, Any]:
        found = await _find_actor(self.session, name)
        if found is not None and found.suppressed:
            return {"success": False, "reason": "whitelisted"}

        dup = await self.session.execute(
            select(ThreatActorGroup).where(func.lower(ThreatActorGroup.name) == name.lower())
        )
        if dup.scalars().first() is not None:
            return {"success": False, "reason": "duplicate"}

        group = ThreatActorGroup(name=name, source="manual")
        self.session.add(group)
        await self.session.flush()
        return {"success": True}

    async def delete_group(
        self, group_id: int, group_name: str, *, actor: str = _TA_ACTOR
    ) -> dict[str, bool]:
        """Hapus grup + whitelist namanya = suppress entitas aktornya (dibuat bila belum ada,
        supaya nama itu tidak pernah dicocokkan lagi, sama seperti `ta_whitelist` v1)."""
        ent = await _find_actor(self.session, group_name)
        if ent is None and alias_norm(group_name or ""):
            ent = await resolve_async(self.session, ACTOR, group_name, source="analyst")
        if ent is not None and not ent.suppressed:
            await set_suppressed_async(self.session, ent.id, True, actor=actor)

        group = await self.session.get(ThreatActorGroup, group_id)
        if group is not None:
            await self.session.delete(group)
        await self.session.flush()
        return {"success": True}

    async def get_ta_stats(self) -> dict[str, Any]:
        total = (
            await self.session.execute(select(func.count()).select_from(ThreatActorGroup))
        ).scalar_one()
        wl_total = (
            await self.session.execute(
                select(func.count())
                .select_from(Entity)
                .where(
                    Entity.type == ACTOR,
                    Entity.suppressed.is_(True),
                    Entity.merged_into_id.is_(None),
                )
            )
        ).scalar_one()
        by_source_rows = (
            await self.session.execute(
                select(ThreatActorGroup.source, func.count())
                .group_by(ThreatActorGroup.source)
                .order_by(func.count().desc())
            )
        ).all()
        by_source = [{"name": s or "unknown", "count": c} for s, c in by_source_rows]
        manual_count = next((r["count"] for r in by_source if r["name"] == "manual"), 0)

        # Aktor di berita yang salah satu alias-nya = nama grup TA (P7c: alias satu entitas = satu
        # baris, nama tampilan `entities.name`).
        m = mention_rows(ACTOR)
        top_news = (
            await self.session.execute(
                select(m.c.name, func.count())
                .where(
                    m.c.article_id.is_not(None),
                    m.c.name != "",
                    m.c.entity_id.in_(entity_ids_matching_column(ACTOR, ThreatActorGroup.name)),
                )
                .group_by(m.c.name)
                .order_by(func.count().desc())
                .limit(500)
            )
        ).all()
        in_news = [{"name": name, "count": count} for name, count in top_news if name]

        return {
            "total_groups": total,
            "total_whitelisted": wl_total,
            "manual_count": manual_count,
            "in_news_count": len(in_news),
            "by_source": by_source,
            "top_in_news": in_news[:10],
        }

    async def list_whitelist(
        self,
        *,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        sort_dir: str = "asc",
    ) -> tuple[list[WhitelistRow], int]:
        added = _suppressed_at()
        stmt = select(Entity.id, func.lower(Entity.name), added).where(
            Entity.type == ACTOR, Entity.suppressed.is_(True), Entity.merged_into_id.is_(None)
        )
        if search:
            stmt = stmt.where(Entity.name.ilike(f"%{search}%"))
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        order_col = added if sort_by == "added_date" else func.lower(Entity.name)
        order = order_col.desc() if sort_dir == "desc" else order_col.asc()
        rows = (
            await self.session.execute(
                stmt.order_by(order, Entity.id).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
        return [WhitelistRow(id=i, name=n, added_date=d) for i, n, d in rows], total

    async def remove_from_whitelist(self, name: str, *, actor: str = _TA_ACTOR) -> bool:
        """Unsuppress aktor yang alias-nya `name`; mention dan alias kembali terlihat (spec 3.4)."""
        ent = await _find_actor(self.session, name)
        if ent is None or not ent.suppressed:
            return False
        await set_suppressed_async(self.session, ent.id, False, actor=actor)
        return True

    async def list_watchlist(
        self,
        *,
        client_id: str,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        sort_dir: str = "asc",
    ) -> tuple[list[WatchlistRow], int]:
        stmt = (
            select(EntityWatch.id, Entity.name, EntityWatch.client_id, EntityWatch.created_at)
            .join(Entity, Entity.id == EntityWatch.entity_id)
            .where(EntityWatch.client_id == client_id, Entity.type == ACTOR)
        )
        if search:
            stmt = stmt.where(Entity.name.ilike(f"%{search}%"))
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        order_col = _WATCHLIST_SORT_FIELDS.get(sort_by, Entity.name)
        order = order_col.desc() if sort_dir == "desc" else order_col.asc()
        rows = (
            await self.session.execute(
                stmt.order_by(order, EntityWatch.id).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
        return [WatchlistRow(id=i, name=n, client_id=c, created_at=d) for i, n, c, d in rows], total

    async def get_watchlist_names(self, client_id: str) -> list[str]:
        result = await self.session.execute(
            select(Entity.name)
            .join(EntityWatch, EntityWatch.entity_id == Entity.id)
            .where(EntityWatch.client_id == client_id, Entity.type == ACTOR)
            .order_by(EntityWatch.id)
        )
        return list(result.scalars().all())

    async def is_watched(self, name: str, client_id: str) -> bool:
        """Apakah aktor dengan alias `name` di-watch `client_id` (cocok per entitas)."""
        ent = await _find_actor(self.session, name)
        if ent is None:
            return False
        found = await self.session.execute(
            select(EntityWatch.id).where(
                EntityWatch.client_id == client_id, EntityWatch.entity_id == ent.id
            )
        )
        return found.first() is not None

    async def get_watchlist_names_unscoped(self) -> list[str]:
        """Port `ioc_service.get_ioc_ta_links()` (Fase 7.4 Grup D) -- legacy
        cek watchlist LINTAS SEMUA client (`ta_db[TA_WATCHLIST_COLLECTION].
        distinct("name")`, tanpa filter client), beda dari model baru yang
        `client_id`-scoped (Fase 2). Asimetri legacy dipertahankan apa
        adanya -- sama pola kayak `AsyncPIRRepo.list_active_unscoped()`.

        P7c: nama + SEMUA alias entitas yang di-watch, huruf kecil (`alias_norm`), supaya
        pencocokan nama di `ioc_ta_links` tetap kena alias apa pun yang tersimpan di IOC."""
        result = await self.session.execute(
            select(EntityAlias.alias_norm)
            .join(EntityWatch, EntityWatch.entity_id == EntityAlias.entity_id)
            .where(EntityAlias.entity_type == ACTOR)
            .distinct()
            .order_by(EntityAlias.alias_norm)
        )
        return list(result.scalars().all())

    async def add_to_watchlist(self, name: str, client_id: str) -> dict[str, Any]:
        """Nama di-resolve ke aktor lewat alias (dibuat bila belum dikenal, seperti v1 yang
        menerima nama apa pun); satu watch per (client, entitas)."""
        ent = await _find_actor(self.session, name)
        if ent is None:
            ent = await resolve_async(self.session, ACTOR, name, source="analyst")
        existing = await self.session.execute(
            select(EntityWatch.id).where(
                EntityWatch.client_id == client_id, EntityWatch.entity_id == ent.id
            )
        )
        if existing.first() is not None:
            return {"success": False, "reason": "already_watched"}
        self.session.add(EntityWatch(client_id=client_id, entity_id=ent.id))
        await self.session.flush()
        return {"success": True}

    async def remove_from_watchlist(self, name: str, client_id: str) -> bool:
        ent = await _find_actor(self.session, name)
        if ent is None:
            return False
        result = await self.session.execute(
            delete(EntityWatch)
            .where(EntityWatch.client_id == client_id, EntityWatch.entity_id == ent.id)
            .returning(EntityWatch.id)
        )
        removed = result.first() is not None
        await self.session.flush()
        return removed


def build_ta_name_pattern(actor_name: str) -> str:
    tokens = [t.strip() for t in re.split(r"[/,]", actor_name) if t.strip()]
    return "|".join(re.escape(t) for t in tokens)


class AsyncTAProfileRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _profiles() -> Any:
        return (
            select(EntityProfile.id, Entity.name, EntityProfile.profile, EntityProfile.generated_at)
            .join(Entity, Entity.id == EntityProfile.entity_id)
            .where(Entity.type == ACTOR)
        )

    @staticmethod
    def _row(r: Any) -> TAProfileRow:
        return TAProfileRow(id=r[0], actor_name=r[1], profile=r[2] or {}, generated_at=r[3])

    async def get_profile(self, actor_name: str) -> TAProfileRow | None:
        """Profil aktor yang alias-nya `actor_name`; `actor_name` hasil = `entities.name`."""
        ent = await _find_actor(self.session, actor_name)
        if ent is None:
            return None
        row = (
            await self.session.execute(self._profiles().where(EntityProfile.entity_id == ent.id))
        ).first()
        return self._row(row) if row is not None else None

    async def list_profiles_by_names(self, actor_names: list[str]) -> list[TAProfileRow]:
        """Case-insensitive lewat alias -- dipakai `crossref` (Bagian 3) buat
        cross-ref sekumpulan nama TA sekaligus. Kontrak v1 dipertahankan: satu baris per nama
        masukan (unik per `alias_norm`) yang punya profil. `actor_name` = nama entitas bila
        masukan hanya beda kapital (seperti v1), selain itu nama masukan itu sendiri: pemanggil
        mengindeks hasil dengan `actor_name.lower()` lalu mencari dengan namanya sendiri. Profil
        dari entitas yang di-resolve lewat alias ("apt36" -> profil "Transparent Tribe")."""
        seen: set[str] = set()
        names = []
        for n in actor_names:
            key = alias_norm(n or "")
            if key and key not in seen:
                seen.add(key)
                names.append(n)
        if not names:
            return []
        result = await self.session.execute(
            self._profiles()
            .add_columns(EntityAlias.alias_norm)
            .join(EntityAlias, EntityAlias.entity_id == Entity.id)
            .where(
                EntityAlias.entity_type == ACTOR,
                EntityAlias.alias_norm.in_({alias_norm(n) for n in names}),
                Entity.merged_into_id.is_(None),
            )
        )
        by_norm = {r[4]: r for r in result.all()}
        rows = []
        for name in names:
            r = by_norm.get(alias_norm(name))
            if r is not None:
                # nama masukan = nama entitas (beda kapital saja): nama tersimpan, seperti v1;
                # alias lain: nama masukan, supaya pemanggil menemukannya
                shown = r[1] if alias_norm(r[1]) == alias_norm(name) else name
                rows.append(
                    TAProfileRow(id=r[0], actor_name=shown, profile=r[2] or {}, generated_at=r[3])
                )
        return rows

    async def save_profile(self, actor_name: str, profile: dict[str, Any]) -> TAProfileRow:
        """Upsert profil per entitas aktor (dibuat bila namanya belum dikenal)."""
        ent = await _find_actor(self.session, actor_name)
        if ent is None:
            ent = await resolve_async(self.session, ACTOR, actor_name, source="analyst")
        existing = (
            await self.session.execute(
                select(EntityProfile).where(EntityProfile.entity_id == ent.id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.profile = profile
            existing.generated_at = datetime.datetime.now(datetime.UTC)
        else:
            existing = EntityProfile(entity_id=ent.id, profile=profile)
            self.session.add(existing)
        await self.session.flush()
        await self.session.refresh(existing)
        return TAProfileRow(
            id=existing.id,
            actor_name=ent.name,
            profile=existing.profile or {},
            generated_at=existing.generated_at,
        )

    async def fetch_recent_news(
        self, actor_name: str, *, days: int = 90, limit: int = 10
    ) -> list[dict[str, Any]]:
        cutoff = datetime.datetime.now(datetime.UTC).date() - datetime.timedelta(days=days)
        pattern = build_ta_name_pattern(actor_name)
        result = await self.session.execute(
            select(Article.title, Article.url, Article.source, Article.posted_on)
            .where(Article.title.op("~*")(pattern), Article.posted_on >= cutoff)
            .order_by(Article.posted_on.desc())
            .limit(limit)
        )
        return [
            {
                "title": r.title,
                "url": r.url,
                "source": r.source,
                "posted_on": r.posted_on.isoformat() if r.posted_on else None,
            }
            for r in result.all()
        ]

    async def get_timeline(self, actor_name: str, *, months: int = 24) -> dict[str, Any]:
        month_list = _build_month_list(months)
        cutoff_date = datetime.date.fromisoformat(month_list[0] + "-01")
        pattern = build_ta_name_pattern(actor_name)

        # `func.to_char(...)` di-assign ke variabel dulu dan dipakai ULANG
        # persis objek yang sama di SELECT+GROUP BY -- kalau ditulis dua
        # kali terpisah (dua panggilan `func.to_char(...)` beda instance),
        # SQLAlchemy nge-generate DUA bind parameter (`$1`/`$4`) yang
        # nilainya sama tapi placeholder-nya beda, dan Postgres nolak itu
        # ("must appear in GROUP BY") karena dicek secara SINTAKS, bukan
        # nilai. Ketauan dari test integrasi, bukan hipotesis.
        article_month = func.to_char(Article.posted_on, "YYYY-MM")
        ment = mention_rows(ACTOR)
        # Nama entitas cocok regex, ATAU salah satu token adalah alias entitas (P7c: "apt36"
        # menghitung artikel "Transparent Tribe").
        tokens = [t.strip() for t in re.split(r"[/,]", actor_name) if t.strip()]
        article_rows = (
            await self.session.execute(
                select(article_month, func.count(func.distinct(Article.id)))
                .select_from(Article)
                .join(ment, ment.c.article_id == Article.id)
                .where(
                    Article.posted_on >= cutoff_date,
                    or_(
                        ment.c.name.op("~*")(pattern),
                        ment.c.entity_id.in_(entity_ids_named(ACTOR, tokens)),
                    ),
                )
                .group_by(article_month)
            )
        ).all()
        # `scan_results.mentioned_group` JSONB ARRAY (bukan scalar) --
        # butuh EXISTS atas `jsonb_array_elements_text` buat cek regex per
        # elemen, gak bisa `.astext` langsung (itu buat scalar JSON value).
        tweet_ta_match = text(
            "EXISTS (SELECT 1 FROM jsonb_array_elements_text("
            "tweets.scan_results->'mentioned_group') AS g WHERE g ~* :pattern)"
        ).bindparams(pattern=pattern)
        tweet_month = func.to_char(Tweet.posted_on, "YYYY-MM")
        tweet_rows = (
            await self.session.execute(
                select(tweet_month, func.count())
                .where(Tweet.posted_on >= cutoff_date, tweet_ta_match)
                .group_by(tweet_month)
            )
        ).all()
        ransom_month = func.to_char(RansomwareVictim.published, "YYYY-MM")
        ransom_rows = (
            await self.session.execute(
                select(ransom_month, func.count())
                .where(
                    RansomwareVictim.published >= cutoff_date,
                    RansomwareVictim.group_name.op("~*")(pattern),
                )
                .group_by(ransom_month)
            )
        ).all()

        art_map: dict[str, int] = {m: c for m, c in article_rows}
        twt_map: dict[str, int] = {m: c for m, c in tweet_rows}
        ran_map: dict[str, int] = {m: c for m, c in ransom_rows}

        article_counts = [art_map.get(m, 0) for m in month_list]
        tweet_counts = [twt_map.get(m, 0) for m in month_list]
        ransom_counts = [ran_map.get(m, 0) for m in month_list]
        total_counts = [
            article_counts[i] + tweet_counts[i] + ransom_counts[i] for i in range(months)
        ]

        last_active_month = next(
            (month_list[i] for i in range(months - 1, -1, -1) if total_counts[i] > 0), None
        )
        last_1 = total_counts[-1] if months >= 1 else 0
        last_3 = sum(total_counts[-3:]) if months >= 3 else sum(total_counts)

        if last_3 == 0:
            dormancy_state = "DORMANT"
        elif last_1 > 0 and sum(total_counts[-3:-1]) == 0 and any(c > 0 for c in total_counts[:-3]):
            dormancy_state = "RESURGENT"
        else:
            dormancy_state = "ACTIVE"

        def _pt_state(idx: int) -> str:
            if total_counts[idx] > 0:
                return "ACTIVE"
            window = total_counts[max(0, idx - 2) : idx + 1]
            return "DORMANT" if all(c == 0 for c in window) else "ACTIVE"

        state_transitions: list[dict[str, str]] = []
        prev_st: str | None = None
        for i, m in enumerate(month_list):
            st = _pt_state(i)
            if prev_st is not None and st != prev_st:
                state_transitions.append({"month": m, "from": prev_st, "to": st})
            prev_st = st

        return {
            "actor": actor_name,
            "months": month_list,
            "article_counts": article_counts,
            "tweet_counts": tweet_counts,
            "ransom_counts": ransom_counts,
            "total_counts": total_counts,
            "dormancy_state": dormancy_state,
            "last_active_month": last_active_month,
            "state_transitions": state_transitions,
            "linked_campaigns": [],
        }

    async def get_dormancy_states(self, actor_names: list[str]) -> dict[str, str]:
        if not actor_names:
            return {}
        cutoff_90 = datetime.datetime.now(datetime.UTC).date() - datetime.timedelta(days=90)
        cutoff_30 = datetime.datetime.now(datetime.UTC).date() - datetime.timedelta(days=30)
        # Nama -> entitas lewat alias (P7c): aktivitas dihitung per entitas, alias apa pun.
        alias_rows = (
            await self.session.execute(
                select(EntityAlias.alias_norm, EntityAlias.entity_id)
                .join(Entity, Entity.id == EntityAlias.entity_id)
                .where(
                    EntityAlias.entity_type == ACTOR,
                    EntityAlias.alias_norm.in_({alias_norm(n) for n in actor_names}),
                    live_entity(),
                )
            )
        ).all()
        entity_of = {norm: eid for norm, eid in alias_rows}

        m = mention_rows(ACTOR)
        rows = (
            await self.session.execute(
                select(
                    m.c.entity_id,
                    func.count(func.distinct(Article.id)),
                    func.sum(case((Article.posted_on >= cutoff_30, 1), else_=0)),
                )
                .select_from(Article)
                .join(m, m.c.article_id == Article.id)
                .where(
                    Article.posted_on >= cutoff_90,
                    m.c.entity_id.in_(set(entity_of.values()) or {-1}),
                )
                .group_by(m.c.entity_id)
            )
        ).all()
        activity = {
            eid: {"total_90": total_90, "total_30": total_30 or 0}
            for eid, total_90, total_30 in rows
        }

        states: dict[str, str] = {}
        for name in actor_names:
            eid = entity_of.get(alias_norm(name))
            rec = activity.get(eid) if eid is not None else None
            if not rec or rec["total_90"] == 0:
                states[name] = "DORMANT"
            elif rec["total_30"] > 0:
                states[name] = "RESURGENT" if rec["total_90"] - rec["total_30"] == 0 else "ACTIVE"
            else:
                states[name] = "DORMANT"
        return states


def _today() -> datetime.date:
    """Titik tunggal "hari ini" buat jendela bulan timeline -- dipisah
    supaya test snapshot bisa nge-freeze tanggal (monkeypatch) tanpa
    nambah dependency freezegun/time-machine."""
    return datetime.date.today()


def _build_month_list(months: int) -> list[str]:
    today = _today()
    result = []
    for i in range(months - 1, -1, -1):
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        result.append(f"{year:04d}-{month:02d}")
    return result
