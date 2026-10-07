"""`tweet_alerts_1h` / `tweet_alerts_30m` / `trending_cve` (Fase 10.E) -- twitterapi.io palsu.

LLM (`classify`) di-patch; `score_with_lists` ASLI (regex funding/zero-day/dst) supaya
routing teruji dengan sinyal sungguhan. HTTP ke MITRE (`_check_cve_vendor`) di-patch.
"""

from __future__ import annotations

import datetime

import httpx
import pytest
from cti_enrich.stages.classify import ClassifyResult, OpenAIQuotaExhausted
from cti_scraper.errors import ParseError
from cti_scrapers.collectors import tweet_alerts
from cti_scrapers.collectors.trending_cve import TrendingCve
from cti_scrapers.collectors.tweet_alerts import TweetAlerts1h, TweetAlerts30m

from tests.unit.scraper_helpers import NOW, json_response, make_ctx

REFERENCE = {"techstack": ["acme"], "threat_actor_groups": ["apt41"], "monitored_people": []}


def tweet(tid: int, text: str, user: str = "blackorbird", **over: object) -> dict:
    base = {
        "id": str(tid), "text": text, "isReply": False,
        "createdAt": "Sat Sep 26 10:00:00 +0000 2026",
        "url": f"https://x.com/{user}/status/{tid}", "author": {"userName": user},
        "entities": {"urls": []},
    }  # fmt: skip
    return {**base, **over}


class Api:
    def __init__(self, tweets: list[dict], status: int = 200) -> None:
        self.tweets, self.status, self.queries = tweets, status, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.queries.append(dict(request.url.params))
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "nope"})
        return json_response({"tweets": self.tweets, "has_next_page": False})


@pytest.fixture(autouse=True)
def _llm_and_mitre(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tweet_alerts,
        "classify",
        lambda text: ClassifyResult(related_cyber="NOT-CYBER" not in text),
    )
    monkeypatch.setattr("cti_enrich.stages.score._check_cve_vendor", lambda cve, stack: False)


def run(cls, api: Api, **kw):
    ctx = make_ctx(cls, api, reference=REFERENCE, **kw)
    return list(cls().fetch(ctx))


# --- pencarian ---------------------------------------------------------------------


def test_all_accounts_go_into_one_query_with_a_window_of_twice_the_interval() -> None:
    api = Api([])

    run(TweetAlerts1h, api)

    [params] = api.queries
    q = params["query"]
    assert (
        q.startswith("(from:blueteamsec1 OR from:DailyDarkWeb OR ") and "OR from:anyrun_app)" in q
    )
    assert "-is:retweet -filter:replies" in q
    since = int(datetime.datetime(2026, 9, 26, 10, 0, tzinfo=datetime.UTC).timestamp())  # NOW-2j
    assert f"since_time:{since}" in q and params["queryType"] == "Latest"


def test_the_two_lists_are_disjoint_and_match_the_old_username_files() -> None:
    a, b = set(TweetAlerts1h.accounts), set(TweetAlerts30m.accounts)

    assert len(a) == 10 and len(b) == 11 and not (a & b)
    assert TweetAlerts30m.window == datetime.timedelta(hours=1)


def test_an_api_error_is_a_visible_parse_error_not_silence() -> None:
    with pytest.raises(ParseError, match="HTTP 401"):
        run(TweetAlerts1h, Api([], status=401))


# --- filter & pesan --------------------------------------------------------------------


def test_a_plain_cyber_tweet_becomes_a_feed_twitter_alert_with_wib_time_and_clean_text() -> None:
    t = tweet(1, "New backdoor found https://t.co/abc123 in the wild\nsecond line <b>x</b>")
    t["entities"] = {
        "urls": [
            {"expanded_url": "https://blog.example/post"},
            {"expanded_url": "https://twitter.com"},
        ]
    }

    [n] = run(TweetAlerts1h, Api([t]))

    assert (n.topic, n.key) == ("feed_twitter", "1:feed_twitter")
    assert "=== <b>NEW TWEET FROM BLACKORBIRD</b> ===" in n.text
    assert "New backdoor found   in the wild second line &lt;b&gt;x&lt;/b&gt;" in n.text
    assert "<b>Posted On</b> : 17:00:00 on 2026-09-26" in n.text  # 10:00 UTC + 7
    assert "<a href='https://x.com/blackorbird/status/1'>See Tweet</a>" in n.text
    assert "<a href='https://blog.example/post'>See Link</a>" in n.text
    assert "twitter.com'>" not in n.text  # link twitter.com polos dibuang


@pytest.mark.parametrize(
    "t",
    [
        tweet(1, "balasan", isReply=True),
        tweet(2, "RT @x: sesuatu"),
        tweet(3, "NOT-CYBER promo diskon"),
        tweet(4, "Startup announces funding round of $20M"),
        tweet(5, "Ransomware Alert: acme has been hit"),
        tweet(6, ""),
    ],
)
def test_noise_is_dropped(t: dict) -> None:
    assert run(TweetAlerts1h, Api([t])) == []


def test_per_account_filters_match_the_old_script() -> None:
    tweets = [
        tweet(1, "New claim on the shame-site for #ransomware: acme", "ecrime_ch"),
        tweet(6, "the shame-site for #ransomware lists victims", "ecrime_ch"),
        tweet(2, "some other post", "ecrime_ch"),
        tweet(3, "no tags here", "H4ckManac"),
        tweet(4, "big #databreach today", "H4ckManac"),
        tweet(5, "kata-kata biasa dengan spasi", "FalconFeedsio"),  # kondisi " " lolos apa saja
    ]
    api = Api(tweets)

    got = {n.key.split(":")[0] for n in run(TweetAlerts30m, api) + run(TweetAlerts1h, api)}

    # ecrime_ch: #1 lolos filter tapi routing membuangnya ("new claim on the shame-site"),
    # #2 kena filter akun, #6 lolos; h4ckmanac: hanya yang bertagar; falconfeedsio: #5 lolos
    assert got == {"4", "5", "6"}


def test_classification_is_skipped_for_tweets_the_cheap_filters_already_drop() -> None:
    calls: list[str] = []

    def spy(text: str) -> ClassifyResult:
        calls.append(text)
        return ClassifyResult(related_cyber=True)

    tweet_alerts.classify = spy  # type: ignore[assignment]  -- dipulihkan monkeypatch fixture
    run(
        TweetAlerts1h,
        Api([tweet(1, "Ransomware Alert: x"), tweet(2, "funding round of $5M"), tweet(3, "ok")]),
    )

    assert calls == ["ok"]


# --- routing ------------------------------------------------------------------------------


def test_topic_follows_the_signals_in_the_tweet() -> None:
    tweets = [
        tweet(1, "A new 0-day exploited in the wild"),
        tweet(2, "Critical flaw allows remote code execution"),
        tweet(3, "APT41 targets telcos"),
        tweet(4, "Attack in Indonesia by criminals", user="threatintel"),
    ]

    topics = {n.key.split(":")[0]: n.topic for n in run(TweetAlerts1h, Api(tweets))}

    # tweet 3 (grup APT) dan 4 (Indonesia) dulu ke `apt`/`apac_indo`; kini tweet umum = satu feed.
    assert topics == {
        "1": "zero_day",
        "2": "tech_stack_unrelated",
        "3": "feed_twitter",
        "4": "feed_twitter",
    }


def test_a_tweet_routed_to_two_topics_becomes_two_notices_with_distinct_keys() -> None:
    [a, b] = run(TweetAlerts1h, Api([tweet(1, "Attack on critical infrastructure today")]))

    assert (a.topic, b.topic) == ("ot", "feed_twitter")
    assert (a.key, b.key) == ("1:ot", "1:feed_twitter")


def test_a_cve_related_to_the_tech_stack_goes_to_tech_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cti_enrich.stages.score._check_cve_vendor", lambda cve, stack: True)

    [n] = run(TweetAlerts1h, Api([tweet(1, "CVE-2026-1111 exploited")]))

    assert n.topic == "tech_stack"


# --- LLM ------------------------------------------------------------------------------------


def test_a_failing_llm_skips_only_that_tweet_so_it_is_retried_next_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def flaky(text: str) -> ClassifyResult:
        if "boom" in text:
            raise ConnectionError("gateway down")
        return ClassifyResult(related_cyber=True)

    monkeypatch.setattr(tweet_alerts, "classify", flaky)

    items = run(TweetAlerts1h, Api([tweet(1, "boom"), tweet(2, "sehat")]))

    assert [i.key for i in items] == ["2:feed_twitter"]


def test_exhausted_llm_quota_stops_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def broke(text: str) -> ClassifyResult:
        raise OpenAIQuotaExhausted("habis")

    monkeypatch.setattr(tweet_alerts, "classify", broke)

    with pytest.raises(OpenAIQuotaExhausted):
        run(TweetAlerts1h, Api([tweet(1, "apa saja")]))


def test_notices_come_oldest_first_and_respect_the_per_run_cap() -> None:
    tweets = [tweet(n, f"tweet {n}") for n in (30, 10, 20)]

    assert [i.key for i in run(TweetAlerts1h, Api(tweets))] == [
        "10:feed_twitter",
        "20:feed_twitter",
        "30:feed_twitter",
    ]
    many = [tweet(n, f"tweet {n}") for n in range(1, 100)]
    assert len(run(TweetAlerts1h, Api(many))) == TweetAlerts1h.meta.max_items == 40


# --- trending_cve ------------------------------------------------------------------------------


def test_trending_cve_counts_each_cve_once_per_tweet_uppercased() -> None:
    api = Api(
        [
            tweet(1, "cve-2026-0001 and CVE-2026-0001 again, plus Cve-2026-0002"),
            tweet(2, "tanpa cve sama sekali"),
            tweet(3, "CVE-2026-0003"),
        ]
    )

    items = run(TrendingCve, api)

    assert [(i.tweet_id, i.cve_ids) for i in items] == [
        ("1", ["CVE-2026-0001", "CVE-2026-0002"]),
        ("3", ["CVE-2026-0003"]),
    ]
    assert all(i.dedup_key() == i.tweet_id for i in items)


def test_trending_cve_query_targets_the_current_year_and_a_thirty_minute_window() -> None:
    api = Api([])

    run(TrendingCve, api)

    q = api.queries[0]["query"]
    since = int(datetime.datetime(2026, 9, 26, 11, 30, tzinfo=datetime.UTC).timestamp())
    assert q == f"CVE-2026- -is:retweet -filter:replies -filter:quote since_time:{since}"
    assert TrendingCve.meta.dedup_ttl_days == 3
    assert NOW.year == 2026


# --- 429 (free tier twitterapi.io: satu request per 5 detik) --------------------------------


class Throttled:
    """API yang membalas 429 untuk `n` panggilan pertama pada halaman KE-2, lalu normal."""

    def __init__(self, throttle_page2: int, page1: list[dict], page2: list[dict]) -> None:
        self.left = throttle_page2
        self.page1, self.page2 = page1, page2
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        self.calls.append("p2" if cursor else "p1")
        if not cursor:
            return json_response({"tweets": self.page1, "has_next_page": True, "next_cursor": "C1"})
        if self.left > 0:
            self.left -= 1
            return httpx.Response(429, json={"error": "rate limited"})
        return json_response({"tweets": self.page2, "has_next_page": False})


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    from cti_scrapers.collectors import _twitterapi

    slept: list[float] = []
    monkeypatch.setattr(_twitterapi.time, "sleep", slept.append)
    return slept


def test_a_429_on_page_two_waits_and_retries_instead_of_failing_the_whole_run(no_sleep) -> None:
    api = Throttled(2, [tweet(1, "satu")], [tweet(2, "dua")])

    items = run(TweetAlerts1h, api)

    assert [i.key for i in items] == ["1:feed_twitter", "2:feed_twitter"]  # kedua halaman terbaca
    assert api.calls == ["p1", "p2", "p2", "p2"]
    assert no_sleep == [6.0, 6.0]


def test_persistent_429_eventually_gives_up_with_the_transient_error(no_sleep) -> None:
    from cti_scraper.errors import TransientFetchError

    api = Throttled(99, [tweet(1, "satu")], [])

    with pytest.raises(TransientFetchError, match="HTTP 429"):
        run(TweetAlerts1h, api)
    assert api.calls.count("p2") == 4 and len(no_sleep) == 3  # 1 + 3 ulangan


def test_other_transient_errors_are_not_retried_by_the_search_helper(no_sleep) -> None:
    from cti_scraper.errors import TransientFetchError

    with pytest.raises(TransientFetchError, match="HTTP 503"):
        run(TrendingCve, Api([], status=503))

    assert no_sleep == []
