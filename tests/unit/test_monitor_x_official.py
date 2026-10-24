"""`monitor_x` dengan opsi `provider=x_official` (2026-10-16).

Prod: kunci twitterapi.io ditolak sejak 2026-10-02 dan `monitor_x` mati dua minggu karena
satu-satunya scraper Twitter tanpa opsi sumber. Jalur twitterapi.io dites di
`test_monitor_x_backoff.py` dan `test_monitor_x_account_wide_errors.py` (tanpa opsi = default =
tidak berubah)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from cti_enrich.stages.classify import ClassifyResult
from cti_scraper.errors import ParseError
from cti_scraper.items import TweetItem
from cti_scraper.options import credential_for, resolve_options
from cti_scrapers.collectors import _twitterapi
from cti_scrapers.feeds import monitor_x
from cti_scrapers.feeds.monitor_x import MonitorX

from tests.unit.scraper_helpers import json_response, make_ctx

OFFICIAL = {"provider": "x_official"}


def reference(last_seen: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "monitored_accounts": ["akun_a", "akun_b"],
        "tweet_last_seen_ids": last_seen or {},
        "techstack": [],
        "threat_actor_groups": [],
        "monitored_people": [],
    }


def post(tid: int, text: str = "tweet") -> dict[str, Any]:
    return {
        "id": str(tid),
        "text": f"{text} {tid}",
        "author_id": "u1",
        "created_at": "2026-09-26T10:00:00.000Z",
    }


class Api:
    """X resmi palsu: balas dengan post milik akun yang ada di `from:<akun>` pada query."""

    def __init__(self, posts_by_account: dict[str, list[dict[str, Any]]], status: int = 200):
        self.posts_by_account, self.status = posts_by_account, status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"title": "nope", "detail": "nope"})
        account = request.url.params["query"].split("from:")[1].split(")")[0]
        posts = self.posts_by_account.get(account, [])
        body = {
            "data": posts,
            "meta": {"result_count": len(posts)},
            "includes": {"users": [{"id": "u1", "username": account}]},
        }
        return json_response(body)


@pytest.fixture(autouse=True)
def _llm_and_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    monkeypatch.setattr(
        monitor_x,
        "classify",
        lambda text, **_: ClassifyResult(related_cyber="NOT-CYBER" not in text),
    )
    slept: list[float] = []
    monkeypatch.setattr(_twitterapi.time, "sleep", slept.append)
    return slept


def run(api: Api, last_seen: dict[str, str] | None = None) -> list[TweetItem]:
    ctx = make_ctx(MonitorX, api, reference=reference(last_seen), options=OFFICIAL)
    return list(MonitorX().fetch(ctx))


def test_each_account_is_searched_on_the_official_api_with_a_six_hour_window(
    _llm_and_sleep: list[float],
) -> None:
    api = Api({"akun_a": [post(1)], "akun_b": [post(2)]})

    items = run(api)

    assert {r.url.host for r in api.requests} == {"api.x.com"}
    assert [r.url.params["query"] for r in api.requests] == [
        "(from:akun_a) -is:retweet -is:reply",
        "(from:akun_b) -is:retweet -is:reply",
    ]
    assert api.requests[0].url.params["start_time"] == "2026-09-26T06:00:00Z"  # NOW 12:00 - 6 jam
    assert [(i.tweet_id, i.author_username) for i in items] == [("1", "akun_a"), ("2", "akun_b")]
    assert _llm_and_sleep == [6.0]  # jeda proaktif antar-akun tetap berlaku (rate_limit 10/minute)


def test_the_stored_item_is_a_full_tweet_row_without_the_profile_x_does_not_send() -> None:
    [item] = run(Api({"akun_a": [post(7, "Acme breach")], "akun_b": []}))

    assert isinstance(item, TweetItem)
    assert item.text == "Acme breach 7" and item.url == "https://x.com/akun_a/status/7"
    assert (item.author_name, item.author_avatar, item.media_urls) == (None, None, [])
    assert set(item.scan_results) >= {"apac_indicator", "cve_list", "ot_status"}


def test_tweets_already_stored_are_skipped_before_scan_and_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classified: list[str] = []

    def spy(text: str, **_: object) -> ClassifyResult:
        classified.append(text)
        return ClassifyResult(related_cyber=True)

    monkeypatch.setattr(monitor_x, "classify", spy)
    api = Api({"akun_a": [post(100), post(150), post(200)], "akun_b": []})

    # kunci last_seen lowercase (resolver); ID 150 = tweet terbaru yang sudah tersimpan
    items = run(api, last_seen={"akun_a": "150"})

    assert [i.tweet_id for i in items] == ["200"]
    assert classified == ["tweet 200"]  # tanpa filter ini tiap run mengklasifikasi ulang jendela


def test_noise_and_non_cyber_tweets_are_dropped_like_the_twitterapi_path() -> None:
    api = Api(
        {
            "akun_a": [
                post(1, "NOT-CYBER promo diskon"),
                post(2, "Startup announces funding round of $20M"),
                post(3, "Ransomware hits a bank"),
            ],
            "akun_b": [],
        }
    )

    assert [i.tweet_id for i in run(api)] == ["3"]


def test_an_official_api_error_fails_the_run_instead_of_looking_like_no_new_tweets() -> None:
    with pytest.raises(ParseError, match="X API HTTP 401"):
        run(Api({}, status=401))


def test_the_credential_follows_the_provider_and_twitterapi_io_stays_the_default() -> None:
    meta = MonitorX.meta

    assert resolve_options(meta) == {"provider": "twitterapi_io"}
    assert credential_for(meta, resolve_options(meta)) == "twitter"
    assert credential_for(meta, resolve_options(meta, OFFICIAL)) == "x"
