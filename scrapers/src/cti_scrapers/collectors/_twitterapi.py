"""Adapter twitterapi.io (sumber Twitter DEFAULT) -- lihat `_twitter.py` buat gambaran
dua-sumbernya. Modul BUKAN scraper; awalan `_` menandai helper internal paket.

Batas free tier twitterapi.io: sekitar SATU request per 5 detik (429 kalau lebih
cepat) -- terukur langsung di staging. Karena itu pencarian beberapa akun digabung
jadi SATU query `(from:a OR from:b ...)`.
"""

from __future__ import annotations

import datetime
import time
from typing import Any

from cti_scraper.base import ScrapeContext
from cti_scraper.errors import ParseError, RateLimited, TransientFetchError
from cti_scraper.ratelimit import parse_rate

from cti_scrapers.collectors._twitter import Tweet, TweetSearch

RATE_LIMIT_BACKOFF_S = 6.0
"""Jeda sebelum mengulang request yang kena 429 (free tier: satu request per 5 detik)."""
RATE_LIMIT_RETRIES = 3

SEARCH_URL = "https://api.twitterapi.io/twitter/tweet/advanced_search"
MAX_PAGES = 5


def compile_query(spec: TweetSearch) -> str:
    """Sintaks twitterapi.io (advanced search): `since_time:<unix>` dan `-filter:...`.
    Urutan bagian dipertahankan persis seperti query yang sudah tervalidasi live."""
    since = int(spec.since.replace(tzinfo=datetime.UTC).timestamp())
    parts: list[str] = []
    if spec.accounts:
        parts.append("(" + " OR ".join(f"from:{a}" for a in spec.accounts) + ")")
    if spec.keyword:
        parts.append(spec.keyword)
    parts += ["-is:retweet", "-filter:replies"]
    if spec.exclude_quotes:
        parts.append("-filter:quote")
    parts.append(f"since_time:{since}")
    return " ".join(parts)


def _get_with_backoff(ctx: ScrapeContext, params: dict[str, str]) -> Any:
    """`ctx.http.get` yang MENUNGGU dan mengulang kalau kena batas laju (maks `RATE_LIMIT_RETRIES`),
    dari DUA sumber berbeda:

    1. `TransientFetchError` "HTTP 429" -- server twitterapi.io sendiri yang menolak. Ditemukan di
       rehearsal staging: pencarian yang butuh 2 halaman gagal total di halaman ke-2 (429) -- run
       dianggap `fetch_error` padahal halaman pertama sudah sukses. Ditunggu `RATE_LIMIT_BACKOFF_S`
       (free tier: kira-kira satu request per 5 detik).
    2. `RateLimited` -- budget LOKAL kita sendiri (`cti_scraper.ratelimit.TokenBucket`, per-domain,
       WAJIB dibagi rata semua scraper yang memukul `api.twitterapi.io`) habis duluan, sebelum
       server sempat menolak. Fase 10.G2: ditemukan `monitor_x` (18 akun berturut-turut) menghabiskan
       jatah SEBELUM kena 429 sama sekali, jadi run selesai status `rate_limited` di akun pertama --
       bukan `fetch_error` di paginasi. Ditunggu sampai jendela fixed-window RESET (`window_s` dari
       `ctx.meta.rate_limit`, deterministik, bukan tebakan) baru diulang.

    Error transien lain (5xx, timeout) tidak diulang di sini -- itu urusan retry Runner."""
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return ctx.http.get(SEARCH_URL, params=params)
        except RateLimited:
            if attempt == RATE_LIMIT_RETRIES:
                raise
            _, window_s = parse_rate(ctx.meta.rate_limit)
            ctx.log.info(
                "twitterapi: budget lokal abis, menunggu jendela reset",
                attempt=attempt + 1,
                wait_s=window_s,
            )
            time.sleep(window_s)
        except TransientFetchError as e:
            if "HTTP 429" not in str(e) or attempt == RATE_LIMIT_RETRIES:
                raise
            ctx.log.info("twitterapi: kena 429, menunggu lalu mengulang", attempt=attempt + 1)
            time.sleep(RATE_LIMIT_BACKOFF_S)
    raise AssertionError("tak tercapai")  # pragma: no cover


def search(ctx: ScrapeContext, spec: TweetSearch, *, max_pages: int = MAX_PAGES) -> list[Tweet]:
    """Semua tweet hasil `spec` (terbaru dulu), sampai `max_pages` halaman.

    Status selain 200 = `ParseError`, BUKAN diam-diam nol tweet: twitterapi.io membalas
    401/403 dengan body `{"error": ...}`, dan `.get("tweets", [])` menjadikan key
    yang salah/kuota habis tampak seperti "tidak ada tweet baru". (429 sudah jadi
    `TransientFetchError` di `ScraperHttpClient`.)"""
    params: dict[str, str] = {"query": compile_query(spec), "queryType": "Latest"}
    tweets: list[Tweet] = []
    for _ in range(max_pages):
        resp = _get_with_backoff(ctx, params)
        if resp.status_code != 200:
            raise ParseError(f"twitterapi.io HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise ParseError(f"twitterapi.io: respons bukan JSON valid -- {e}") from e
        tweets.extend(to_tweet(raw) for raw in data.get("tweets", []))
        if data.get("has_next_page") and data.get("next_cursor"):
            params["cursor"] = data["next_cursor"]
        else:
            break
    return tweets


def parse_created_at(raw: str) -> datetime.datetime | None:
    """ "Mon May 11 13:00:57 +0000 2026" -> naif UTC."""
    try:
        return datetime.datetime.strptime(raw, "%a %b %d %H:%M:%S +0000 %Y")
    except (ValueError, TypeError):
        return None


def to_tweet(raw: dict[str, Any]) -> Tweet:
    author = raw.get("author") or {}
    user = str(author.get("userName", ""))
    links = tuple(
        str(u["expanded_url"])
        for u in (raw.get("entities") or {}).get("urls", []) or []
        if u.get("expanded_url")
    )
    media = tuple(
        str(m["media_url_https"])
        for m in (raw.get("extendedEntities") or {}).get("media", []) or []
        if m.get("media_url_https")
    )
    return Tweet(
        id=str(raw["id"]),
        text=str(raw.get("text", "")),
        username=user,
        created_at=parse_created_at(raw.get("createdAt", "")),
        url=str(raw.get("url") or f"https://twitter.com/{user}/status/{raw['id']}"),
        links=links,
        is_reply=bool(raw.get("isReply")),
        author_name=author.get("name") or None,
        author_avatar=author.get("profilePicture") or None,
        author_followers=int(author.get("followers") or 0) if "followers" in author else None,
        lang=raw.get("lang") or None,
        media_urls=media,
    )
