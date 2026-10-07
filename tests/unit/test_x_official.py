"""Adapter API resmi X v2 (`_x_official.py`) + pemilihan sumber per-scraper.

Semua lewat transport HTTP palsu -- tidak ada panggilan ke api.x.com. Bentuk respons ditulis
mengikuti dokumentasi `GET /2/tweets/search/recent` (`data[]`, `includes.users`, `meta`);
kecocokan dengan API sungguhan diverifikasi terpisah, live di staging.
"""

from __future__ import annotations

import datetime
from typing import Any

import httpx
import pytest
import structlog
from cti_enrich.stages.classify import ClassifyResult
from cti_scraper.base import ConfigError
from cti_scraper.errors import ParseError, TransientFetchError
from cti_scrapers.collectors import _twitter as tw
from cti_scrapers.collectors import _x_official as x
from cti_scrapers.collectors import tweet_alerts
from cti_scrapers.collectors.trending_cve import TrendingCve
from cti_scrapers.collectors.tweet_alerts import TweetAlerts1h

from tests.unit.scraper_helpers import NOW, json_response, make_ctx

OFFICIAL = {"provider": "x_official"}
SINCE = datetime.datetime(2026, 9, 26, 10, 0, 0)


def post(tid: int, text: str, author: str = "u1", **over: Any) -> dict[str, Any]:
    base = {
        "id": str(tid),
        "text": text,
        "author_id": author,
        "created_at": "2026-09-26T10:00:00.000Z",
    }
    return {**base, **over}


def page(
    posts: list[dict], users: dict[str, str] | None = None, next_token: str | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"data": posts, "meta": {"result_count": len(posts)}}
    if next_token:
        body["meta"]["next_token"] = next_token
    body["includes"] = {
        "users": [{"id": i, "username": n} for i, n in (users or {"u1": "blackorbird"}).items()]
    }
    return body


class Api:
    """Transport palsu: giliran respons per panggilan, mencatat semua request."""

    def __init__(self, *responses: httpx.Response | dict[str, Any]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return r if isinstance(r, httpx.Response) else json_response(r)

    @property
    def params(self) -> list[dict[str, str]]:
        return [dict(r.url.params) for r in self.requests]


def search(api: Api, spec: tw.TweetSearch | None = None) -> list[tw.Tweet]:
    ctx = make_ctx(TweetAlerts1h, api, options=OFFICIAL)
    return x.search(ctx, spec or tw.TweetSearch(since=SINCE, accounts=("blackorbird",)))


# --- query & parameter ------------------------------------------------------------------


def test_query_uses_x_syntax_and_time_goes_into_start_time_not_the_query() -> None:
    spec = tw.TweetSearch(since=SINCE, accounts=("a", "B"))

    assert x.compile_query(spec) == "(from:a OR from:B) -is:retweet -is:reply"
    assert "since_time" not in x.compile_query(spec)
    assert (
        x.compile_query(tw.TweetSearch(since=SINCE, keyword="CVE-2026-", exclude_quotes=True))
        == "CVE-2026- -is:retweet -is:reply -is:quote"
    )


def test_request_targets_the_official_host_with_iso_start_time_and_expansions() -> None:
    api = Api(page([]))

    search(api)

    [req] = api.requests
    assert (req.url.host, req.url.path) == ("api.x.com", "/2/tweets/search/recent")
    p = api.params[0]
    assert p["start_time"] == "2026-09-26T10:00:00Z"
    assert p["max_results"] == "100"
    assert p["expansions"] == "author_id" and p["user.fields"] == "username"
    assert {"created_at", "entities", "referenced_tweets", "note_tweet"} <= set(
        p["tweet.fields"].split(",")
    )


# --- bentuk respons -> Tweet --------------------------------------------------------------


def test_a_post_becomes_a_neutral_tweet_with_username_from_includes() -> None:
    entities = {"urls": [{"expanded_url": "https://blog.example/p"}, {"url": "https://t.co/x"}]}
    api = Api(page([post(7, "halo dunia", entities=entities)]))

    [t] = search(api)

    assert t == tw.Tweet(
        id="7",
        text="halo dunia",
        username="blackorbird",
        created_at=datetime.datetime(2026, 9, 26, 10, 0, 0),
        url="https://x.com/blackorbird/status/7",
        links=("https://blog.example/p",),  # entri tanpa expanded_url dibuang
        is_reply=False,
    )


def test_text_is_html_unescaped_so_the_telegram_message_is_not_double_escaped() -> None:
    api = Api(page([post(1, "Tom &amp; Jerry &lt;b&gt; &gt; x")]))

    [t] = search(api)

    assert t.text == "Tom & Jerry <b> > x"


def test_a_long_post_uses_note_tweet_text_and_its_own_entities() -> None:
    long = post(
        1,
        "teks terpotong…",
        note_tweet={
            "text": "teks LENGKAP yang panjang",
            "entities": {"urls": [{"expanded_url": "https://dalam-note.example"}]},
        },
        entities={"urls": [{"expanded_url": "https://di-teks-pendek.example"}]},
    )

    [t] = search(Api(page([long])))

    assert t.text == "teks LENGKAP yang panjang"
    assert t.links == ("https://dalam-note.example",)


def test_reply_flag_comes_from_referenced_tweets() -> None:
    refs = {"referenced_tweets": [{"type": "replied_to", "id": "9"}]}
    quoted = {"referenced_tweets": [{"type": "quoted", "id": "9"}]}

    a, b = search(Api(page([post(1, "balasan", **refs), post(2, "kutipan", **quoted)])))

    assert (a.is_reply, b.is_reply) == (True, False)


def test_a_post_whose_author_is_missing_still_gets_a_working_url() -> None:
    api = Api(page([post(5, "tanpa penulis", author="tidak-ada")]))

    [t] = search(api)

    assert (t.username, t.url) == ("", "https://x.com/i/status/5")


def test_malformed_posts_are_skipped_and_an_unparsable_date_is_none() -> None:
    api = Api(page([{"text": "tanpa id"}, "bukan-objek", post(3, "ok", created_at="kemarin")]))

    [t] = search(api)

    assert (t.id, t.created_at) == ("3", None)


def test_an_empty_result_is_an_empty_list_not_an_error() -> None:
    assert search(Api({"meta": {"result_count": 0}})) == []


# --- paginasi & biaya -----------------------------------------------------------------------


def test_the_second_page_is_requested_with_the_next_token_and_stops_when_it_runs_out() -> None:
    api = Api(page([post(1, "a")], next_token="TOK1"), page([post(2, "b")]))

    tweets = search(api)

    assert [t.id for t in tweets] == ["1", "2"]
    assert "next_token" not in api.params[0] and api.params[1]["next_token"] == "TOK1"


def test_pages_are_capped_because_every_post_read_costs_money() -> None:
    """Halaman ke-3 TIDAK diminta walau masih ada `next_token`; run mencatat pemotongannya."""
    api = Api(
        page([post(1, "a")], next_token="T1"),
        page([post(2, "b")], next_token="T2"),
        page([post(3, "c")]),
    )

    with structlog.testing.capture_logs() as logs:
        tweets = search(api)

    assert len(api.requests) == x.MAX_PAGES == 2
    assert [t.id for t in tweets] == ["1", "2"]
    assert any(entry["event"] == "x_official_truncated" for entry in logs)


def test_every_search_logs_how_many_posts_were_read_and_the_estimated_cost() -> None:
    api = Api(page([post(1, "a"), post(2, "b"), post(3, "c"), post(4, "d")]))

    with structlog.testing.capture_logs() as logs:
        search(api)

    [entry] = [e for e in logs if e["event"] == "x_official_search"]
    assert (entry["pages"], entry["posts_read"]) == (1, 4)
    assert entry["est_cost_usd"] == pytest.approx(4 * x.USD_PER_POST_READ)


# --- error API: keras, bukan "nol tweet" -----------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"title": "Unauthorized", "detail": "Unauthorized"}, "HTTP 401: Unauthorized"),
        (402, {"title": "CreditsDepleted", "detail": "Your credits are gone"}, "CreditsDepleted"),
        (403, {"title": "Forbidden", "detail": "no access to this endpoint"}, "no access"),
        (400, {"errors": [{"message": "Invalid query: unmatched paren"}]}, "unmatched paren"),
    ],
)
def test_api_errors_are_visible_parse_errors_with_the_reason(
    status: int, body: dict, expected: str
) -> None:
    api = Api(httpx.Response(status, json=body))

    with pytest.raises(ParseError, match=expected):
        search(api)


def test_non_json_bodies_and_unknown_shapes_are_parse_errors() -> None:
    with pytest.raises(ParseError, match="bukan JSON"):
        search(Api(httpx.Response(200, content=b"<html>")))
    with pytest.raises(ParseError, match="tanpa 'data'/'meta'"):
        search(Api({"unexpected": True}))
    with pytest.raises(ParseError, match="bukan list"):
        search(Api({"data": {"id": "1"}, "meta": {}}))


def test_429_is_left_to_the_runner_to_retry_with_its_own_backoff() -> None:
    """Jendela rate limit X itu 15 MENIT -- tidur 6 detik seperti twitterapi.io tak ada gunanya."""
    api = Api(httpx.Response(429, json={"title": "Too Many Requests"}))

    with pytest.raises(TransientFetchError, match="HTTP 429"):
        search(api)
    assert len(api.requests) == 1


# --- pemilihan sumber -----------------------------------------------------------------------------


def test_the_default_provider_is_twitterapi_io_and_official_only_when_chosen() -> None:
    io_api = Api({"tweets": [], "has_next_page": False})
    ctx = make_ctx(TweetAlerts1h, io_api)  # tanpa opsi apa pun
    tw.search(ctx, tw.TweetSearch(since=SINCE))
    assert io_api.requests[0].url.host == "api.twitterapi.io"

    x_api = Api(page([]))
    tw.search(make_ctx(TweetAlerts1h, x_api, options=OFFICIAL), tw.TweetSearch(since=SINCE))
    assert x_api.requests[0].url.host == "api.x.com"


def test_an_unknown_provider_fails_loudly() -> None:
    ctx = make_ctx(TweetAlerts1h, Api(page([])), options={"provider": "mastodon"})

    with pytest.raises(ConfigError, match="tidak dikenal"):
        tw.search(ctx, tw.TweetSearch(since=SINCE))


def test_the_scrapers_declare_the_choice_and_default_to_twitterapi_io() -> None:
    for cls in (TweetAlerts1h, TrendingCve):
        [option] = cls.meta.options
        assert option.key == "provider" and option.default == tw.TWITTERAPI_IO
        assert {c.value: c.credential for c in option.choices} == {
            "twitterapi_io": "twitter",
            "x_official": "x",
        }
        assert cls.meta.credential == "twitter"  # = kredensial pilihan default
    assert "PERINGATAN BIAYA" in TrendingCve.meta.options[0].description


# --- end-to-end lewat scraper ---------------------------------------------------------------------


REFERENCE = {"techstack": ["acme"], "threat_actor_groups": ["apt41"], "monitored_people": []}


@pytest.fixture(autouse=True)
def _llm_and_mitre(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tweet_alerts, "classify", lambda text: ClassifyResult(related_cyber=True))
    monkeypatch.setattr("cti_enrich.stages.score._check_cve_vendor", lambda cve, stack: False)


def test_tweet_alerts_works_end_to_end_on_the_official_api() -> None:
    api = Api(
        page(
            [
                post(
                    2,
                    "New backdoor https://t.co/abc &amp; more",
                    entities={"urls": [{"expanded_url": "https://blog.example/p"}]},
                ),
                post(1, "balasan orang", referenced_tweets=[{"type": "replied_to", "id": "0"}]),
            ]
        )
    )
    ctx = make_ctx(TweetAlerts1h, api, reference=REFERENCE, options=OFFICIAL)

    [n] = list(TweetAlerts1h().fetch(ctx))

    assert (n.topic, n.key) == (
        "feed_twitter",
        "2:feed_twitter",
    )  # kunci = id tweet, sama seperti twitterapi.io
    assert "NEW TWEET FROM BLACKORBIRD" in n.text
    assert "New backdoor   &amp; more" in n.text  # `&amp;` sekali, bukan `&amp;amp;`
    assert "<a href='https://x.com/blackorbird/status/2'>See Tweet</a>" in n.text
    assert "<a href='https://blog.example/p'>See Link</a>" in n.text
    assert "<b>Posted On</b> : 17:00:00 on 2026-09-26" in n.text
    assert api.params[0]["start_time"] == "2026-09-26T10:00:00Z"  # NOW (12:00) - 2 jam


def test_trending_cve_on_the_official_api_searches_the_current_year_without_quotes() -> None:
    """Sintaks ini terbukti valid di API X asli (probe staging: kutip/tanpa kutip -> hasil sama)."""
    api = Api(page([post(1, "cve-2026-0001 rame"), post(2, "tanpa cve")]))
    ctx = make_ctx(TrendingCve, api, options=OFFICIAL)

    [item] = list(TrendingCve().fetch(ctx))

    assert api.params[0]["query"] == "CVE-2026- -is:retweet -is:reply -is:quote"
    assert api.params[0]["start_time"] == "2026-09-26T11:30:00Z"
    assert (item.tweet_id, item.cve_ids) == ("1", ["CVE-2026-0001"])
    assert NOW.year == 2026


def test_trending_cve_does_not_ask_for_authors_because_users_may_be_billed_separately() -> None:
    # tanpa `expansions` X tidak mengirim `includes` sama sekali (terverifikasi di API asli)
    api = Api({"data": [{"id": "1", "text": "cve-2026-0001"}], "meta": {"result_count": 1}})
    ctx = make_ctx(TrendingCve, api, options=OFFICIAL)

    [item] = list(TrendingCve().fetch(ctx))

    assert "expansions" not in api.params[0] and "user.fields" not in api.params[0]
    assert item.url == "https://x.com/i/status/1"  # tanpa username -> URL generik yang tetap valid


def test_authors_are_requested_by_default_and_when_the_scraper_needs_the_username() -> None:
    assert x._params(tw.TweetSearch(since=SINCE))["expansions"] == "author_id"
    assert (
        x._params(tw.TweetSearch(since=SINCE, with_author=False))
        .keys()
        .isdisjoint({"expansions", "user.fields"})
    )
    # twitterapi.io tidak terpengaruh flag ini: query-nya sama persis
    from cti_scrapers.collectors import _twitterapi as io

    assert io.compile_query(tw.TweetSearch(since=SINCE, with_author=False)) == io.compile_query(
        tw.TweetSearch(since=SINCE)
    )
