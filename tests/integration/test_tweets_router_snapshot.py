"""Snapshot test `routers/tweets.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`)."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.models.tweet import Tweet
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?fetched_at$": (str,),
    },
    regex=True,
    strict=False,
)


async def _seed_tweet(session: AsyncSession) -> None:
    session.add(
        Tweet(
            tweet_id="1234567890",
            url="https://twitter.com/example/status/1234567890",
            text="APT41 targeting manufacturing sector",
            author_username="threatintel",
            author_name="Threat Intel",
            posted_on=datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC),
            lang="en",
            scan_results={"apac_indicator": True, "mentioned_group": ["Apt41"]},
            confidence_score=80,
        )
    )
    await session.flush()


async def test_tweet_stats(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_tweet(api_session)
    resp = await api_client.get("/api/tweets/stats", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_list_tweets_signal_and_has_cve_params(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_tweet(api_session)
    for path in ("/api/tweets", "/api/tweets/stats"):
        for signal in ("ot", "zero_day", "databreach", "report"):
            resp = await api_client.get(path, params={"signal": signal}, headers=auth_header())
            assert resp.status_code == 200, (path, signal)
        resp = await api_client.get(path, params={"has_cve": "true"}, headers=auth_header())
        assert resp.status_code == 200
        resp = await api_client.get(path, params={"signal": "bogus"}, headers=auth_header())
        assert resp.status_code == 422


async def test_list_tweets(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_tweet(api_session)
    resp = await api_client.get("/api/tweets", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def _seed_day_edges(session: AsyncSession) -> None:
    """3 tweet di sekitar 30 Sep: 13:20 UTC (= 20:20 WIB, 30 Sep), 23:30 UTC
    (= 06:30 WIB TANGGAL 1 Okt) dan 29 Sep 18:00 UTC (= 01:00 WIB 30 Sep)."""
    for tid, ts in (
        ("2001", datetime.datetime(2026, 9, 30, 13, 20, tzinfo=datetime.UTC)),
        ("2002", datetime.datetime(2026, 9, 30, 23, 30, tzinfo=datetime.UTC)),
        ("2003", datetime.datetime(2026, 9, 29, 18, 0, tzinfo=datetime.UTC)),
    ):
        session.add(
            Tweet(
                tweet_id=tid,
                url=f"https://x.com/rst_cloud/status/{tid}",
                text="ransomware alert",
                author_username="rst_cloud",
                posted_on=ts,
                scan_results={},
            )
        )
    await session.flush()


async def test_list_tweets_same_day_range_is_inclusive(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """QA BUG-B5: From=To=2026-09-30 dulu 0 hasil -- "To" ke-parse jadi
    00:00 dan seluruh harinya kebuang. Tanpa `tz` = hari UTC."""
    await _seed_day_edges(api_session)
    params = {"posted_on_start": "2026-09-30", "posted_on_end": "2026-09-30"}
    resp = await api_client.get("/api/tweets", params=params, headers=auth_header())
    assert resp.status_code == 200
    assert {t["tweet_id"] for t in resp.json()["tweets"]} == {"2001", "2002"}
    stats = await api_client.get("/api/tweets/stats", params=params, headers=auth_header())
    assert stats.json()["total"] == 2


async def test_list_tweets_day_bounds_follow_user_timezone(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """Hari "30 Sep" buat user WIB = 29 Sep 17:00 UTC s/d 30 Sep 17:00 UTC."""
    await _seed_day_edges(api_session)
    params = {
        "posted_on_start": "2026-09-30",
        "posted_on_end": "2026-09-30",
        "tz": "Asia/Jakarta",
    }
    resp = await api_client.get("/api/tweets", params=params, headers=auth_header())
    assert resp.status_code == 200
    assert {t["tweet_id"] for t in resp.json()["tweets"]} == {"2001", "2003"}


async def test_list_tweets_author_with_at_and_bad_params(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """QA BUG-B6 lewat HTTP + validasi input tanggal/zona."""
    await _seed_day_edges(api_session)
    resp = await api_client.get(
        "/api/tweets", params={"author": "@rst_cloud"}, headers=auth_header()
    )
    assert resp.json()["total"] == 3

    # Datetime lengkap tetap instan persis (inklusif), kompatibel caller lama.
    resp = await api_client.get(
        "/api/tweets", params={"posted_on_end": "2026-09-30T13:20:00Z"}, headers=auth_header()
    )
    assert {t["tweet_id"] for t in resp.json()["tweets"]} == {"2001", "2003"}

    bad_tz = await api_client.get(
        "/api/tweets",
        params={"posted_on_end": "2026-09-30", "tz": "Mars/Base"},
        headers=auth_header(),
    )
    assert bad_tz.status_code == 422
    bad_date = await api_client.get(
        "/api/tweets", params={"posted_on_end": "30/09/2026"}, headers=auth_header()
    )
    assert bad_date.status_code == 422
