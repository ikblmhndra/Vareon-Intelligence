"""AsyncTARepo (groups/whitelist/watchlist) + AsyncTAProfileRepo (profil
LLM+timeline+dormancy) -- port `ScraperNewsWeb/app/services/ta_service.py`
+ `ta_profile_service.py`. Fase 7.3 (router `ta_groups`, Bagian 3).

Daftar nama TA utama (`ThreatActorGroup`, Fase 5) dipakai bareng
`cti_enrich.stages.score` -- lihat docstring `db/models/ta.py` soal
kenapa gak ada tabel baru terpisah buat itu."""

from __future__ import annotations

import datetime
import re
from typing import Any

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.db.models.article import Article, ArticleThreatActor
from cti_core.db.models.ransomware import RansomwareVictim
from cti_core.db.models.ta import TAProfile, TAWatchlistEntry, TAWhitelistEntry
from cti_core.db.models.threat_reference import ThreatActorGroup
from cti_core.db.models.tweet import Tweet

_GROUP_SORT_FIELDS = {
    "name": ThreatActorGroup.name,
    "added_date": ThreatActorGroup.created_at,
    "source": ThreatActorGroup.source,
}
_WHITELIST_SORT_FIELDS = {"name": TAWhitelistEntry.name, "added_date": TAWhitelistEntry.added_date}
_WATCHLIST_SORT_FIELDS = {"name": TAWatchlistEntry.name, "added_date": TAWatchlistEntry.created_at}


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
        wl = await self.session.execute(
            select(TAWhitelistEntry).where(TAWhitelistEntry.name == name.lower())
        )
        if wl.scalars().first() is not None:
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

    async def delete_group(self, group_id: int, group_name: str) -> dict[str, bool]:
        existing = await self.session.execute(
            select(TAWhitelistEntry).where(TAWhitelistEntry.name == group_name.lower())
        )
        if existing.scalars().first() is None:
            self.session.add(TAWhitelistEntry(name=group_name.lower()))

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
            await self.session.execute(select(func.count()).select_from(TAWhitelistEntry))
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

        all_names = (await self.session.execute(select(ThreatActorGroup.name))).scalars().all()
        group_names_lower = {n.lower() for n in all_names if n}

        top_news = (
            await self.session.execute(
                select(ArticleThreatActor.threat_actor, func.count())
                .where(ArticleThreatActor.threat_actor != "")
                .group_by(ArticleThreatActor.threat_actor)
                .order_by(func.count().desc())
                .limit(500)
            )
        ).all()
        in_news = [
            {"name": name, "count": count}
            for name, count in top_news
            if name and name.lower() in group_names_lower
        ]

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
    ) -> tuple[list[TAWhitelistEntry], int]:
        stmt = select(TAWhitelistEntry)
        if search:
            stmt = stmt.where(TAWhitelistEntry.name.ilike(f"%{search}%"))
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        order_col = _WHITELIST_SORT_FIELDS.get(sort_by, TAWhitelistEntry.name)
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

    async def remove_from_whitelist(self, name: str) -> bool:
        result = await self.session.execute(
            select(TAWhitelistEntry).where(TAWhitelistEntry.name == name.lower())
        )
        entry = result.scalars().first()
        if entry is None:
            return False
        await self.session.delete(entry)
        await self.session.flush()
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
    ) -> tuple[list[TAWatchlistEntry], int]:
        stmt = select(TAWatchlistEntry).where(TAWatchlistEntry.client_id == client_id)
        if search:
            stmt = stmt.where(TAWatchlistEntry.name.ilike(f"%{search}%"))
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        order_col = _WATCHLIST_SORT_FIELDS.get(sort_by, TAWatchlistEntry.name)
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

    async def get_watchlist_names(self, client_id: str) -> list[str]:
        result = await self.session.execute(
            select(TAWatchlistEntry.name).where(TAWatchlistEntry.client_id == client_id)
        )
        return list(result.scalars().all())

    async def get_watchlist_names_unscoped(self) -> list[str]:
        """Port `ioc_service.get_ioc_ta_links()` (Fase 7.4 Grup D) -- legacy
        cek watchlist LINTAS SEMUA client (`ta_db[TA_WATCHLIST_COLLECTION].
        distinct("name")`, tanpa filter client), beda dari model baru yang
        `client_id`-scoped (Fase 2). Asimetri legacy dipertahankan apa
        adanya -- sama pola kayak `AsyncPIRRepo.list_active_unscoped()`."""
        result = await self.session.execute(select(TAWatchlistEntry.name))
        return list(result.scalars().all())

    async def add_to_watchlist(self, name: str, client_id: str) -> dict[str, Any]:
        existing = await self.session.execute(
            select(TAWatchlistEntry).where(
                func.lower(TAWatchlistEntry.name) == name.lower(),
                TAWatchlistEntry.client_id == client_id,
            )
        )
        if existing.scalars().first() is not None:
            return {"success": False, "reason": "already_watched"}
        self.session.add(TAWatchlistEntry(name=name, client_id=client_id))
        await self.session.flush()
        return {"success": True}

    async def remove_from_watchlist(self, name: str, client_id: str) -> bool:
        result = await self.session.execute(
            select(TAWatchlistEntry).where(
                func.lower(TAWatchlistEntry.name) == name.lower(),
                TAWatchlistEntry.client_id == client_id,
            )
        )
        entry = result.scalars().first()
        if entry is None:
            return False
        await self.session.delete(entry)
        await self.session.flush()
        return True


def build_ta_name_pattern(actor_name: str) -> str:
    tokens = [t.strip() for t in re.split(r"[/,]", actor_name) if t.strip()]
    return "|".join(re.escape(t) for t in tokens)


class AsyncTAProfileRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_profile(self, actor_name: str) -> TAProfile | None:
        result = await self.session.execute(
            select(TAProfile).where(func.lower(TAProfile.actor_name) == actor_name.lower())
        )
        return result.scalars().first()

    async def list_profiles_by_names(self, actor_names: list[str]) -> list[TAProfile]:
        """Case-insensitive `IN` -- dipakai `crossref` (Bagian 3) buat
        cross-ref sekumpulan nama TA sekaligus."""
        if not actor_names:
            return []
        lowered = [n.lower() for n in actor_names]
        result = await self.session.execute(
            select(TAProfile).where(func.lower(TAProfile.actor_name).in_(lowered))
        )
        return list(result.scalars().all())

    async def save_profile(self, actor_name: str, profile: dict[str, Any]) -> TAProfile:
        existing = await self.get_profile(actor_name)
        if existing is not None:
            existing.profile = profile
            existing.generated_at = datetime.datetime.now(datetime.UTC)
            await self.session.flush()
            return existing
        row = TAProfile(actor_name=actor_name, profile=profile)
        self.session.add(row)
        await self.session.flush()
        return row

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
        article_rows = (
            await self.session.execute(
                select(article_month, func.count(func.distinct(Article.id)))
                .join(Article.threat_actors)
                .where(
                    Article.posted_on >= cutoff_date,
                    ArticleThreatActor.threat_actor.op("~*")(pattern),
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
        lower_names = {n.lower() for n in actor_names}

        rows = (
            await self.session.execute(
                select(
                    func.lower(ArticleThreatActor.threat_actor),
                    func.count(func.distinct(Article.id)),
                    func.sum(case((Article.posted_on >= cutoff_30, 1), else_=0)),
                )
                .select_from(Article)
                .join(Article.threat_actors)
                .where(Article.posted_on >= cutoff_90)
                .group_by(func.lower(ArticleThreatActor.threat_actor))
            )
        ).all()
        activity = {
            name: {"total_90": total_90, "total_30": total_30 or 0}
            for name, total_90, total_30 in rows
            if name in lower_names
        }

        states: dict[str, str] = {}
        for name in actor_names:
            rec = activity.get(name.lower())
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
