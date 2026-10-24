"""Port CRUD-baca dari `ScraperNewsWeb/app/routers/tweets.py`. `GET /balance`
(cek kuota API twitterapi.io) SENGAJA gak diport -- passthrough eksternal
doang, gak nyimpen/nge-query data platform, gak genting buat inti."""

from __future__ import annotations

import datetime
import zoneinfo

from cti_core.db.models.tweet import Tweet
from cti_core.db.repositories.tweet import AsyncTweetRepo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import get_db, require_auth, require_permission
from cti_api.schemas.tweet import TweetListResponse, TweetOut

router = APIRouter(
    prefix="/api/tweets",
    tags=["tweets"],
    dependencies=[Depends(require_permission("view_tweets")), Depends(require_auth)],
)

_DATE_ONLY_LEN = len("YYYY-MM-DD")
_START_DESC = (
    "`YYYY-MM-DD` = mulai tengah malam hari itu di zona `tz`; datetime ISO 8601 = instan persis."
)
_END_DESC = (
    "`YYYY-MM-DD` = INKLUSIF sampai akhir hari itu di zona `tz`; "
    "datetime ISO 8601 = batas atas inklusif (instan persis)."
)
_TZ_DESC = "Zona IANA (mis. `Asia/Jakarta`) buat batas hari `YYYY-MM-DD`. Default UTC."


def _zone(tz: str | None) -> datetime.tzinfo:
    if not tz:
        return datetime.UTC
    try:
        return zoneinfo.ZoneInfo(tz)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid timezone: {tz}") from exc


def _parse_bound(raw: str, name: str) -> datetime.date | datetime.datetime:
    try:
        if len(raw) == _DATE_ONLY_LEN:
            return datetime.date.fromisoformat(raw)
        return datetime.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {name}: {raw}") from exc


def _aware(dt: datetime.datetime, zone: datetime.tzinfo) -> datetime.datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=zone)


def _date_bounds(
    start: str | None, end: str | None, tz: str | None
) -> tuple[datetime.datetime | None, datetime.datetime | None, datetime.datetime | None]:
    """`(posted_on_start, posted_on_end, posted_before)` buat repo.

    Dulu param-nya `datetime` polos: tanggal "To" dari date picker
    (`2026-09-30`) ke-parse jadi `2026-09-30 00:00` UTC dan dipakai `<=`,
    jadi seluruh hari terakhir kebuang -- From=To=hari yang sama selalu 0
    hasil (QA BUG-B5). Sekarang tanggal polos = SATU HARI PENUH di zona
    `tz` (zona browser user, sama kayak waktu tweet yang dirender lokal di
    `tweet-card.tsx`): start = tengah malam hari itu, end = `<` tengah
    malam hari berikutnya. Datetime lengkap tetap dipakai apa adanya
    (inklusif, naive dianggap zona `tz`) -- kompatibel sama caller lama."""
    zone = _zone(tz)
    start_dt = end_dt = before_dt = None
    if start:
        v = _parse_bound(start, "posted_on_start")
        if isinstance(v, datetime.datetime):
            start_dt = _aware(v, zone)
        else:
            start_dt = datetime.datetime.combine(v, datetime.time.min, tzinfo=zone)
    if end:
        v = _parse_bound(end, "posted_on_end")
        if isinstance(v, datetime.datetime):
            end_dt = _aware(v, zone)
        else:
            next_day = v + datetime.timedelta(days=1)
            before_dt = datetime.datetime.combine(next_day, datetime.time.min, tzinfo=zone)
    return start_dt, end_dt, before_dt


def _serialize(t: Tweet) -> TweetOut:
    scan = t.scan_results
    return TweetOut(
        id=t.id,
        tweet_id=t.tweet_id,
        url=t.url,
        text=t.text,
        author_username=t.author_username,
        author_name=t.author_name or "",
        author_avatar=t.author_avatar or "",
        author_followers=t.author_followers or 0,
        posted_on=t.posted_on.isoformat() if t.posted_on else "",
        lang=t.lang or "en",
        media_urls=t.media_urls,
        fetched_at=t.fetched_at.isoformat() if t.fetched_at else "",
        apac_indicator=bool(scan.get("apac_indicator", False)),
        mentioned_group=scan.get("mentioned_group", []),
        mentioned_apac_country=scan.get("mentioned_apac_country", []),
        mentioned_apac_people=scan.get("mentioned_apac_people", []),
        cve_list=scan.get("cve_list", []),
        zero_day_list=scan.get("zero_day_list", []),
        databreach_list=scan.get("databreach_list", []),
        ot_status=bool(scan.get("ot_status", False)),
        report_status=bool(scan.get("report_status", False)),
        confidence=t.confidence_score,
        industries_impacted=t.industries_impacted,
        victim_countries=t.victim_countries,
        actor_countries=t.actor_countries,
        confirmed_incident=t.confirmed_incident,
        incident_confidence=t.incident_confidence,
        incident_indicators=t.incident_indicators,
        victim_name=t.victim_name,
    )


@router.get("/stats")
async def tweet_stats(
    search: str | None = None,
    author: str | None = None,
    lang: str | None = None,
    posted_on_start: str | None = Query(None, description=_START_DESC),
    posted_on_end: str | None = Query(None, description=_END_DESC),
    tz: str | None = Query(None, description=_TZ_DESC),
    apac_only: bool = Query(False),
    ot_only: bool = Query(False),
    confirmed_only: bool = Query(False),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    start, end, before = _date_bounds(posted_on_start, posted_on_end, tz)
    return await AsyncTweetRepo(session).get_stats(
        search=search,
        author=author,
        lang=lang,
        posted_on_start=start,
        posted_on_end=end,
        posted_before=before,
        apac_only=apac_only,
        ot_only=ot_only,
        confirmed_only=confirmed_only,
    )


@router.get("", response_model=TweetListResponse)
async def list_tweets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    author: str | None = None,
    lang: str | None = None,
    posted_on_start: str | None = Query(None, description=_START_DESC),
    posted_on_end: str | None = Query(None, description=_END_DESC),
    tz: str | None = Query(None, description=_TZ_DESC),
    apac_only: bool = Query(False),
    ot_only: bool = Query(False),
    confirmed_only: bool = Query(False),
    session: AsyncSession = Depends(get_db),
) -> TweetListResponse:
    start, end, before = _date_bounds(posted_on_start, posted_on_end, tz)
    tweets, total = await AsyncTweetRepo(session).list_filtered(
        page=page,
        page_size=page_size,
        search=search,
        author=author,
        lang=lang,
        posted_on_start=start,
        posted_on_end=end,
        posted_before=before,
        apac_only=apac_only,
        ot_only=ot_only,
        confirmed_only=confirmed_only,
    )
    return TweetListResponse(
        tweets=[_serialize(t) for t in tweets], total=total, page=page, page_size=page_size
    )
