"""TweetRepo -- satu-satunya jalur tulis `tweets`. Gantiin `dbMongo.
upsert_tweet`/`tweet_exists` (`$setOnInsert`-only, gak pernah update tweet
yang udah ada -- dipertahankan di sini: sekali masuk, field mesin TIDAK
di-refresh, beda dari `ArticleRepo.upsert` yang emang didesain buat re-scrape.
Alasannya sama kayak lama: tweet gak berubah isinya setelah diposting,
beda dari artikel yang bisa di-edit penulisnya).

`AsyncTweetRepo`/`AsyncMonitoredAccountRepo` (Fase 7.3, router `tweets.py`/
`monitored_accounts.py`) BARU -- permukaan BACA (tweet) + CRUD penuh
(monitored account, jalur tulis BARU karena tabelnya emang cuma dibaca
scraper `monitorX.py` sebelum ini). Jalur tulis `tweets` sendiri TETAP
`TweetRepo` sync di atas (Celery/CLI monitor, Fase 5), gak disentuh."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.models.tweet import MonitoredAccount, Tweet


class TweetRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def exists(self, tweet_id: str) -> bool:
        return (
            self.session.execute(select(Tweet.id).where(Tweet.tweet_id == tweet_id)).first()
            is not None
        )

    def insert(self, *, tweet_id: str, url: str, text: str, **fields: Any) -> Tweet | None:
        """`None` kalau `tweet_id` udah ada -- caller cek `exists()` duluan
        kalau perlu tau alasannya, di sini insert aja/no-op diam-diam,
        setara return value `upsert_tweet()` lama (`True` kalau baru)."""
        existing = self.session.execute(select(Tweet.id).where(Tweet.tweet_id == tweet_id)).first()
        if existing is not None:
            return None

        row = Tweet(tweet_id=tweet_id, url=url, text=text, **fields)
        self.session.add(row)
        self.session.flush()
        return row

    def get_last_seen_id(self, author_username: str) -> str | None:
        """Ganti `state.json` (`monitorX.py::load_state/save_state`) --
        tweet ID terbesar yang udah tersimpan buat akun ini, dipakai
        sebagai `since_id` query berikutnya. MAX numerik, bukan MAX string
        (ID Twitter numerik tapi disimpen sebagai string)."""
        rows = (
            self.session.execute(
                select(Tweet.tweet_id).where(Tweet.author_username == author_username)
            )
            .scalars()
            .all()
        )
        if not rows:
            return None
        return max(rows, key=int)


def _apply_tweet_filters(
    stmt: Select[tuple[Any, ...]],
    *,
    search: str | None,
    author: str | None,
    lang: str | None,
    posted_on_start: datetime.datetime | None = None,
    posted_on_end: datetime.datetime | None = None,
    posted_before: datetime.datetime | None = None,
    apac_only: bool,
    ot_only: bool,
    confirmed_only: bool,
) -> Select[tuple[Any, ...]]:
    """`apac_indicator`/`ot_status` ada DI DALAM `scan_results` JSONB
    (bukan kolom top-level) -- lihat docstring `Tweet.scan_results`
    (Fase 5). `.as_boolean()` operator JSONB Postgres, ekuivalen
    `query["apac_indicator"] = True` Mongo lama. Dipakai `list_filtered`
    DAN `get_stats` -- dua-duanya kena filter yang sama persis (port
    perilaku lama).

    `posted_on_end` = batas atas INKLUSIF (`<=`, instan persis);
    `posted_before` = batas atas EKSKLUSIF (`<`) -- dipakai buat "sampai
    akhir hari X" (= `<` tengah malam hari X+1), lihat `routers/tweets.py`.
    Dulu cuma ada `posted_on_end` dan tanggal "To" dari UI ke-parse jadi
    00:00 hari itu, jadi seluruh hari terakhir kebuang (QA BUG-B5).

    `author`: `@` di depan dibuang (QA BUG-B6) -- placeholder UI "@handle…"
    dan `author_username` disimpan TANPA `@` (lihat
    `AsyncMonitoredAccountRepo.create`), jadi "@rst_cloud" dulu 0 hasil."""
    if search:
        stmt = stmt.where(Tweet.text.ilike(f"%{search}%"))
    author = author.strip().lstrip("@").strip() if author else None
    if author:
        stmt = stmt.where(Tweet.author_username.ilike(f"%{author}%"))
    if lang:
        stmt = stmt.where(Tweet.lang == lang)
    if posted_on_start is not None:
        stmt = stmt.where(Tweet.posted_on >= posted_on_start)
    if posted_on_end is not None:
        stmt = stmt.where(Tweet.posted_on <= posted_on_end)
    if posted_before is not None:
        stmt = stmt.where(Tweet.posted_on < posted_before)
    if apac_only:
        stmt = stmt.where(Tweet.scan_results["apac_indicator"].as_boolean())
    if ot_only:
        stmt = stmt.where(Tweet.scan_results["ot_status"].as_boolean())
    if confirmed_only:
        stmt = stmt.where(Tweet.confirmed_incident.is_(True))
    return stmt


class AsyncTweetRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_filtered(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        author: str | None = None,
        lang: str | None = None,
        posted_on_start: datetime.datetime | None = None,
        posted_on_end: datetime.datetime | None = None,
        posted_before: datetime.datetime | None = None,
        apac_only: bool = False,
        ot_only: bool = False,
        confirmed_only: bool = False,
    ) -> tuple[list[Tweet], int]:
        stmt = _apply_tweet_filters(
            select(Tweet),
            search=search,
            author=author,
            lang=lang,
            posted_on_start=posted_on_start,
            posted_on_end=posted_on_end,
            posted_before=posted_before,
            apac_only=apac_only,
            ot_only=ot_only,
            confirmed_only=confirmed_only,
        )
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        list_stmt = (
            # `id` tiebreaker: tanpa ini urutan tweet ber-`posted_on` sama gak
            # deterministik antar-page (pola sama QA BUG-B4 ransomware).
            stmt.order_by(Tweet.posted_on.desc().nulls_last(), Tweet.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(list_stmt)
        return list(result.scalars().all()), total

    async def list_top_between(
        self, *, posted_on_start: datetime.datetime, posted_before: datetime.datetime, limit: int
    ) -> tuple[list[Tweet], int]:
        """`(tweet terkuat di [posted_on_start, posted_before), maksimal limit, total sebenarnya)`.

        Dipakai recap mingguan: seminggu bisa ratusan tweet, jadi yang masuk prompt dipilih DI
        SQL (`LIMIT`), bukan dimuat semua lalu dipotong. Urutan sinyal: insiden terkonfirmasi,
        lalu `incident_confidence` (NULL terakhir, sama dengan sort recap harian), lalu terbaru.
        `posted_before` EKSKLUSIF, sama dengan `_apply_tweet_filters`."""
        window = _apply_tweet_filters(
            select(Tweet),
            search=None,
            author=None,
            lang=None,
            posted_on_start=posted_on_start,
            posted_before=posted_before,
            apac_only=False,
            ot_only=False,
            confirmed_only=False,
        )
        total = (
            await self.session.execute(select(func.count()).select_from(window.subquery()))
        ).scalar_one()
        result = await self.session.execute(
            window.order_by(
                Tweet.confirmed_incident.desc(),
                Tweet.incident_confidence.desc().nulls_last(),
                Tweet.posted_on.desc().nulls_last(),
                Tweet.id.desc(),
            ).limit(limit)
        )
        return list(result.scalars().all()), total

    async def get_stats(
        self,
        *,
        search: str | None = None,
        author: str | None = None,
        lang: str | None = None,
        posted_on_start: datetime.datetime | None = None,
        posted_on_end: datetime.datetime | None = None,
        posted_before: datetime.datetime | None = None,
        apac_only: bool = False,
        ot_only: bool = False,
        confirmed_only: bool = False,
    ) -> dict[str, object]:
        base_filter = _apply_tweet_filters(
            select(Tweet.id, Tweet.author_username),
            search=search,
            author=author,
            lang=lang,
            posted_on_start=posted_on_start,
            posted_on_end=posted_on_end,
            posted_before=posted_before,
            apac_only=apac_only,
            ot_only=ot_only,
            confirmed_only=confirmed_only,
        ).subquery()

        total = (
            await self.session.execute(select(func.count()).select_from(base_filter))
        ).scalar_one()
        top_stmt = (
            select(base_filter.c.author_username, func.count())
            .group_by(base_filter.c.author_username)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_authors = (await self.session.execute(top_stmt)).all()
        return {
            "total": total,
            "top_authors": [{"author": a, "count": c} for a, c in top_authors],
        }


class AsyncMonitoredAccountRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[MonitoredAccount]:
        result = await self.session.execute(
            select(MonitoredAccount).order_by(MonitoredAccount.username)
        )
        return list(result.scalars().all())

    async def get(self, username: str) -> MonitoredAccount | None:
        result = await self.session.execute(
            select(MonitoredAccount).where(MonitoredAccount.username == username)
        )
        return result.scalar_one_or_none()

    async def create(
        self, username: str, display_name: str = "", notes: str = ""
    ) -> MonitoredAccount:
        username = username.lstrip("@").strip().lower()
        if await self.get(username) is not None:
            raise ValueError(f"@{username} already monitored")
        account = MonitoredAccount(
            username=username, display_name=display_name.strip(), notes=notes.strip()
        )
        self.session.add(account)
        await self.session.flush()
        return account

    async def remove(self, username: str) -> bool:
        username = username.lstrip("@").strip().lower()
        account = await self.get(username)
        if account is None:
            return False
        await self.session.delete(account)
        await self.session.flush()
        return True

    async def toggle(self, username: str, active: bool) -> bool:
        username = username.lstrip("@").strip().lower()
        account = await self.get(username)
        if account is None:
            return False
        account.active = active
        await self.session.flush()
        return True
