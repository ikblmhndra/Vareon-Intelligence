"""`tweet_alerts_1h` / `tweet_alerts_30m` / `trending_cve` (Fase 10.E) -- twitterapi.io palsu.

Scraper tidak memanggil LLM dan tidak merutekan topik (itu pekerjaan worker, job `tweet`):
yang dites di sini filter murah, bentuk `TweetJobItem`, dan `build_message`. `score_with_lists`
ASLI (regex funding/zero-day/dst). HTTP ke MITRE (`_check_cve_vendor`) di-patch.
"""

from __future__ import annotations

import datetime
import html

import httpx
import pytest
from cti_enrich.stages.score import ScoreResult, score_with_lists
from cti_scraper import sinks
from cti_scraper.errors import ParseError
from cti_scraper.items import TweetJobItem
from cti_scrapers.collectors import _twitter as tw
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
    monkeypatch.setattr("cti_enrich.stages.score._check_cve_vendor", lambda cve, stack: False)


def run(cls, api: Api, **kw):
    """Semua `TweetJobItem` dari `fetch()`."""
    ctx = make_ctx(cls, api, reference=REFERENCE, **kw)
    return list(cls().fetch(ctx))


def message_of(t: dict, **kw) -> str:
    """Pesan Telegram yang dibangun worker: `build_message` dari tweet netral + scan-nya."""
    ctx = make_ctx(TweetAlerts1h, Api([t]), reference=REFERENCE)
    [parsed] = tw.by_id(tw.search(ctx, tw.TweetSearch(since=NOW, accounts=("blackorbird",))))
    scan = score_with_lists(
        title=parsed.text, body="", techstack=["acme"], group_list=["apt41"], apac_people_list=[]
    )
    return tweet_alerts.build_message(parsed, scan, **kw)


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


def test_a_plain_cyber_tweet_message_has_wib_time_and_clean_text() -> None:
    t = tweet(1, "New backdoor found https://t.co/abc123 in the wild\nsecond line <b>x</b>")
    t["entities"] = {
        "urls": [
            {"expanded_url": "https://blog.example/post"},
            {"expanded_url": "https://twitter.com"},
        ]
    }

    text = message_of(t)

    assert "=== <b>NEW TWEET FROM BLACKORBIRD</b> ===" in text
    assert "New backdoor found   in the wild second line &lt;b&gt;x&lt;/b&gt;" in text
    assert "<b>Posted On</b> : 17:00:00 on 2026-09-26" in text  # 10:00 UTC + 7
    assert "<a href='https://x.com/blackorbird/status/1'>See Tweet</a>" in text
    assert "<a href='https://blog.example/post'>See Link</a>" in text
    assert "twitter.com'>" not in text  # link twitter.com polos dibuang


def test_tweet_alerts_yields_one_job_item_per_kept_tweet_with_notify() -> None:
    tweets = [
        tweet(1, "balasan", isReply=True),
        tweet(2, "RT @x: sesuatu"),
        tweet(3, "Startup announces funding round of $20M"),
        tweet(4, "Ransomware Alert: acme has been hit"),
        tweet(5, "Attack on critical infrastructure today"),
        tweet(6, "A new 0-day exploited in the wild"),
    ]

    items = run(TweetAlerts1h, Api(tweets))

    assert all(isinstance(i, TweetJobItem) and i.notify for i in items)
    assert [i.tweet_id for i in items] == [
        "5",
        "6",
    ]  # balasan/RT/pendanaan/Ransomware Alert out
    ot, zero_day = items
    assert zero_day.routing["zero_day_list"] and not ot.routing["zero_day_list"]
    assert set(ot.routing) == {
        "msg_data", "cve_list", "related_tech_status", "report_status", "ot_status",
        "databreach_list", "zero_day_list",
    }  # fmt: skip
    # Worker tidak punya scan untuk `build_message`: pesan utuh (routing) dan pesan Telegram
    # (dibatasi 4096) ikut di item (Ruling 4).
    raw = tweet(5, "Attack on critical infrastructure today")
    assert ot.routing["msg_data"] == message_of(raw, limit=None)
    assert ot.notice_text == message_of(raw)
    assert ot.author_username == "blackorbird" and ot.text.startswith("Attack on")
    assert {"apac_indicator", "cve_list", "ot_status", "mentioned_group"} <= set(ot.scan_results)


def test_routing_carries_related_tech_status_from_the_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cti_enrich.stages.score._check_cve_vendor", lambda cve, stack: True)

    [item] = run(TweetAlerts1h, Api([tweet(1, "CVE-2026-1111 exploited")]))

    assert item.routing["related_tech_status"] is True
    assert item.routing["cve_list"] == ["cve-2026-1111"]  # apa adanya dari scan


def test_the_job_item_carries_profile_and_media_of_the_source() -> None:
    full = tweet(
        7,
        "Acme confirmed a breach",
        author={
            "userName": "blackorbird",
            "name": "Black Orbird",
            "profilePicture": "https://pbs.example/a.jpg",
            "followers": 1234,
        },
        lang="en",
        extendedEntities={"media": [{"media_url_https": "https://pbs.example/m.jpg"}]},
    )

    [item] = run(TweetAlerts1h, Api([full]))

    assert (item.author_name, item.author_avatar, item.author_followers) == (
        "Black Orbird",
        "https://pbs.example/a.jpg",
        1234,
    )
    assert item.lang == "en" and item.media_urls == ["https://pbs.example/m.jpg"]
    assert item.posted_on == datetime.datetime(2026, 9, 26, 10, 0, 0)
    assert item.dedup_key() == "7"


def test_a_source_without_profile_data_still_yields_with_empty_profile() -> None:
    [item] = run(TweetAlerts1h, Api([tweet(1, "plain tweet")]))

    assert (item.author_name, item.author_avatar, item.author_followers) == (None, None, None)
    assert item.media_urls == []


@pytest.mark.parametrize(
    "t",
    [
        tweet(1, "balasan", isReply=True),
        tweet(2, "RT @x: sesuatu"),
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

    got = {n.tweet_id for n in run(TweetAlerts30m, api) + run(TweetAlerts1h, api)}

    # ecrime_ch: #1 dan #6 lolos (routing di worker yang membuang "new claim on the shame-site"),
    # #2 kena filter akun; h4ckmanac: hanya yang bertagar; falconfeedsio: #5 lolos
    assert got == {"1", "4", "5", "6"}


# --- batas Telegram: satu notice <= 4096 karakter ------------------------------------------------

TRUNCATED = "… [truncated, see Tweet URL]"
TWEET_LABEL = "<b>Tweet</b> : "


def tweet_line(text: str) -> str:
    """Isi baris `Tweet` pada pesan (sudah di-escape), apa adanya termasuk penanda terpotong."""
    start = text.index(TWEET_LABEL) + len(TWEET_LABEL)
    return text[start : text.index("\n<b>Posted On</b>")]


def links_of(*urls: str) -> dict:
    return {"urls": [{"expanded_url": u} for u in urls]}


def test_the_alert_limit_is_the_one_the_notice_sink_enforces() -> None:
    assert tweet_alerts._TELEGRAM_LIMIT == sinks._TELEGRAM_TEXT_LIMIT == 4096


def test_a_short_tweet_message_is_byte_for_byte_what_it_was_before_the_limit() -> None:
    assert message_of(tweet(1, "hello")) == (
        "\n=== <b>NEW TWEET FROM BLACKORBIRD</b> ===\n"
        "<b>Author</b> : blackorbird\n"
        "<b>Tweet</b> : hello\n"
        "<b>Posted On</b> : 17:00:00 on 2026-09-26\n"
        "<b>Tweet URL</b> : <a href='https://x.com/blackorbird/status/1'>See Tweet</a>\n"
    )


def test_many_long_links_are_kept_whole_while_the_whole_message_still_fits() -> None:
    urls = [f"https://blog.example/{i}/" + "p" * 100 for i in range(12)]  # ~1900 karakter tautan

    text = message_of(tweet(1, "short", entities=links_of(*urls)))

    assert text.count("See Link") == 12 and "more" not in text and "truncated" not in text


def test_a_6000_char_tweet_is_cut_to_fit_and_keeps_every_other_line() -> None:
    body = ("word " * 1200).strip()  # 5999 karakter
    t = tweet(1, body, entities=links_of("https://blog.example/post"))

    text = message_of(t)

    assert 4000 < len(text) <= 4096  # memakai ruang yang ada, bukan dipotong berlebihan
    assert tweet_line(text).endswith(TRUNCATED)
    assert "=== <b>NEW TWEET FROM BLACKORBIRD</b> ===" in text
    assert "<b>Author</b> : blackorbird" in text
    assert "<b>Posted On</b> : 17:00:00 on 2026-09-26" in text
    assert "<a href='https://x.com/blackorbird/status/1'>See Tweet</a>" in text
    assert "<a href='https://blog.example/post'>See Link</a>" in text


@pytest.mark.parametrize("shift", range(6))  # menggeser posisi potong ke tiap offset entitas
def test_escaped_text_is_cut_on_whole_entities_never_inside_one(shift: int) -> None:
    body = "a" * shift + "<&>\"'" * 2000  # tiap karakter jadi 4-6 karakter setelah escape

    text = message_of(tweet(1, body))

    assert len(text) <= 4096
    shown = tweet_line(text).removesuffix(TRUNCATED)
    assert shown != tweet_line(text)  # memang terpotong
    # Entitas terbelah ("&am") tinggal literal waktu di-unescape dan bukan lagi awalan teks asli.
    assert body.startswith(html.unescape(shown)) and len(html.unescape(shown)) > 500
    assert text.count("<a ") == text.count("</a>")
    assert text.count("<b>") == text.count("</b>")


def test_a_long_link_list_is_limited_without_breaking_a_tag_and_keeps_the_tweet_url() -> None:
    urls = [f"https://blog.example/{i}/" + "p" * 120 for i in range(40)]  # ~7000 karakter tautan
    t = tweet(1, "x " * 1750, entities=links_of(*urls))  # 3500 karakter teks

    text = message_of(t)

    assert len(text) <= 4096
    assert "<a href='https://x.com/blackorbird/status/1'>See Tweet</a>" in text
    assert "<a href='https://blog.example/0/" in text  # tautan pertama tetap ada
    assert text.count("<a ") == text.count("</a>")
    assert 0 < text.count("See Link") < 40 and " || +" in text and " more" in text


def test_long_mention_lists_are_limited_and_the_message_still_fits() -> None:
    scan = ScoreResult(
        mentioned_group=[f"group-{i}" for i in range(300)],
        mentioned_countries=[f"country-{i}" for i in range(300)],
        mentioned_apac_people=[f"person-{i}" for i in range(300)],
    )
    t = tw.Tweet(
        id="1", text="x " * 3000, username="blackorbird", created_at=NOW,
        url="https://x.com/blackorbird/status/1",
    )  # fmt: skip

    msg = tweet_alerts.build_message(t, scan)

    assert len(msg) <= 4096
    assert "<b>Mentioned Group</b> : Group-0 || Group-1" in msg
    assert "<b>Mentioned APAC Country/People</b> : Country-0" in msg
    assert msg.count(" more") == 2  # satu ringkasan "+N more" per daftar yang dipotong
    assert "<a href='https://x.com/blackorbird/status/1'>See Tweet</a>" in msg


def test_the_ransomware_filter_and_the_job_text_cover_the_whole_tweet() -> None:
    filler = "analysis " * 600  # 5400 karakter: penanda di ekor berada di luar bagian yang dikirim

    [kept] = run(TweetAlerts1h, Api([tweet(1, filler + "#threatreport")]))
    dropped = run(TweetAlerts1h, Api([tweet(2, filler + "Ransomware Alert: acme")]))

    assert kept.text.endswith("#threatreport")  # route_tweet di worker membaca teks utuh
    assert "#threatreport" not in message_of(tweet(1, filler + "#threatreport"))
    assert dropped == []


def test_a_truncated_message_leaves_the_job_item_with_the_full_tweet() -> None:
    body = ("word " * 1200).strip()

    [item] = run(TweetAlerts1h, Api([tweet(1, body)]))

    assert item.text == body
    assert tweet_line(message_of(tweet(1, body))).endswith(TRUNCATED)


def test_the_per_run_cap_is_200_job_items() -> None:
    many = [tweet(n, f"tweet {n}") for n in range(1, 260)]

    items = run(TweetAlerts1h, Api(many))

    assert len(items) == TweetAlerts1h.meta.max_items == TweetAlerts30m.meta.max_items == 200


def test_job_items_come_oldest_first() -> None:
    tweets = [tweet(n, f"tweet {n}") for n in (30, 10, 20)]

    assert [i.tweet_id for i in run(TweetAlerts1h, Api(tweets))] == ["10", "20", "30"]


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

    assert [i.tweet_id for i in items] == ["1", "2"]  # kedua halaman terbaca
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


def test_long_tweet_routes_on_the_full_message_but_notices_the_capped_one() -> None:
    """`#threatreport` di ekor post panjang: routing membaca `msg_data` utuh, Telegram menerima
    `notice_text` yang muat batas 4096."""
    long_text = "word " * 1500 + "#threatreport"

    [item] = run(TweetAlerts1h, Api([tweet(1, long_text)]))

    assert "#threatreport" in item.routing["msg_data"]
    assert item.notice_text is not None and len(item.notice_text) <= 4096
    assert "#threatreport" not in item.notice_text
