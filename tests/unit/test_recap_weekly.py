"""Unit test logika murni recap MINGGUAN (`cti_api.services.recap`, #21 PR 2 dan 3) -- tanpa DB,
tanpa LLM: jendela Senin-Minggu, penolakan pekan yang belum selesai, penyusun agregat/prompt, hasil
"tidak ada aktivitas", id artikel dan seksi review di prompt, dan pemasangan grounding pada
keluaran model. Yang butuh Postgres (kolektor, cache, migrasi) ada di
`tests/integration/test_recap_service.py`."""

from __future__ import annotations

import copy
import datetime
import hashlib
import re
from types import SimpleNamespace as NS
from typing import Any
from unittest.mock import MagicMock

import pytest
from cti_api.services import grounding
from cti_api.services import recap as svc

D = datetime.date


# --- jendela Senin-Minggu --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("week_start", "week_end"),
    [
        (D(2026, 10, 5), D(2026, 10, 11)),
        (D(2026, 9, 28), D(2026, 10, 4)),  # melintasi pergantian bulan
        (D(2025, 12, 29), D(2026, 1, 4)),  # melintasi pergantian tahun
        (D(2024, 2, 26), D(2024, 3, 3)),  # memuat 29 Februari (kabisat)
    ],
)
def test_week_window_is_monday_to_sunday(week_start: D, week_end: D) -> None:
    assert svc.week_window(week_start) == (week_start, week_end)
    assert week_start.weekday() == 0 and week_end.weekday() == 6


@pytest.mark.parametrize("offset", range(1, 7))
def test_week_window_rejects_every_day_that_is_not_a_monday(offset: int) -> None:
    not_monday = D(2026, 10, 5) + datetime.timedelta(days=offset)

    with pytest.raises(svc.RecapWindowError, match="must be a Monday"):
        svc.week_window(not_monday)


def test_a_window_error_is_a_value_error_so_callers_can_catch_either() -> None:
    assert issubclass(svc.RecapWindowError, ValueError)


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (D(2026, 11, 2), D(2026, 10, 26)),  # run terjadwal 2 Nov: pekan 26 Okt-1 Nov
        (D(2026, 10, 12), D(2026, 10, 5)),
        (D(2026, 10, 14), D(2026, 10, 5)),  # run telat (worker mati hari Senin): pekan yang sama
        (D(2026, 10, 11), D(2026, 9, 28)),  # Minggu 11 Okt belum lewat: pekan 5-11 belum selesai
        (D(2026, 1, 1), D(2025, 12, 22)),  # pergantian tahun
    ],
)
def test_last_finished_week_start(today: D, expected: D) -> None:
    assert svc.last_finished_week_start(today) == expected


@pytest.mark.parametrize("day", range(14))
def test_last_finished_week_is_always_a_monday_whose_sunday_is_already_over(day: int) -> None:
    today = D(2026, 10, 5) + datetime.timedelta(days=day)

    start = svc.last_finished_week_start(today)
    _, end = svc.week_window(start)

    assert end < today
    assert today - end <= datetime.timedelta(days=7)  # dan itu pekan TERAKHIR yang selesai


def test_a_week_is_finished_only_once_its_sunday_is_over_in_utc() -> None:
    sunday = D(2026, 10, 11)

    svc.ensure_week_finished(sunday, today=D(2026, 10, 12))  # Senin 00:15 UTC: boleh
    for today in (D(2026, 10, 8), D(2026, 10, 10), sunday):  # termasuk Minggunya sendiri
        with pytest.raises(svc.RecapWindowError, match="not finished yet"):
            svc.ensure_week_finished(sunday, today=today)


def test_the_unfinished_week_message_says_when_it_can_be_generated() -> None:
    with pytest.raises(svc.RecapWindowError, match=r"from 2026-10-12"):
        svc.ensure_week_finished(D(2026, 10, 11), today=D(2026, 10, 9))


async def test_generate_weekly_recap_refuses_before_touching_the_database_or_the_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pekan yang belum selesai ditolak SEBELUM query apa pun (juga dengan force): kalau tidak,
    pekan bolong tersimpan dan run terjadwal Senin mengembalikannya sebagai cache."""
    monkeypatch.setattr(svc, "_today_utc", lambda: D(2026, 10, 9))  # Jumat
    monkeypatch.setattr(svc, "get_llm_client", MagicMock(side_effect=AssertionError("LLM")))
    session = MagicMock()

    for week_start, force in [(D(2026, 10, 5), False), (D(2026, 10, 5), True)]:
        with pytest.raises(svc.RecapWindowError, match="not finished yet"):
            await svc.generate_weekly_recap(session, week_start, force)
    with pytest.raises(svc.RecapWindowError, match="must be a Monday"):
        await svc.generate_weekly_recap(session, D(2026, 10, 6))

    assert session.mock_calls == []


# --- penyusun agregat ------------------------------------------------------------------------


_POSTED = D(2026, 10, 1)


def _article(
    id: int,
    *,
    confirmed: bool = False,
    score: int | None = 50,
    source: str = "CISA",
    posted: D = _POSTED,
) -> NS:
    return NS(
        id=id,
        title=f"story {id}",
        url=f"https://example.com/story/{id}",
        source=source,
        confirmed_incident=confirmed,
        confidence_score=score,
        posted_on=posted,
        threat_actors=[],
    )


def _ids(lines: list[tuple[NS, int]]) -> list[int]:
    return [a.id for a, _ in lines]


def test_articles_are_ranked_confirmed_incident_then_confidence_then_cluster_then_source() -> None:
    pool = [
        _article(1, score=60, source="Vice"),
        _article(2, score=60, source="CISA"),  # seri dengan 1: sumber andal menang
        _article(3, score=60, source="Vice"),  # seri dengan 1 dan 2, tapi anggota klaster
        _article(4, score=90),
        _article(5, score=10, confirmed=True),  # terkonfirmasi: di atas confidence 90
    ]

    lines = svc._rank_weekly_articles(pool, {3: (0, 5)})

    assert _ids(lines) == [5, 4, 3, 2, 1]
    assert dict((a.id, size) for a, size in lines) == {5: 0, 4: 0, 3: 5, 2: 0, 1: 0}


def test_articles_of_one_cluster_collapse_to_one_line_that_carries_the_cluster_size() -> None:
    pool = [_article(i, score=80 - i) for i in range(1, 6)]
    clusters = {1: (0, 4), 2: (0, 4), 3: (0, 4), 4: (1, 2), 5: (1, 2)}

    lines = svc._rank_weekly_articles(pool, clusters)

    assert [(a.id, size) for a, size in lines] == [(1, 4), (4, 2)]  # wakil terkuat tiap klaster


def test_article_cap_applies_after_the_collapse_not_before(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_WEEKLY_MAX_ARTICLES", 2)
    pool = [
        _article(1, score=90),
        _article(2, score=89),
        _article(3, score=88),
        _article(4, score=10),
    ]
    # 1 dan 2 satu klaster: tanpa collapse, dua slot habis oleh klaster yang sama.
    lines = svc._rank_weekly_articles(pool, {1: (0, 3), 2: (0, 3)})

    assert _ids(lines) == [1, 3]


def test_ranking_is_stable_for_equal_signals_newest_first_then_highest_id() -> None:
    pool = [
        _article(1, posted=D(2026, 10, 1)),
        _article(2, posted=D(2026, 10, 3)),
        _article(3, posted=D(2026, 10, 3)),
    ]

    assert _ids(svc._rank_weekly_articles(pool, {})) == [3, 2, 1]


def _inputs(**over: object) -> svc.WeeklyInputs:
    base: dict[str, object] = dict(
        start=D(2026, 9, 28),
        end=D(2026, 10, 4),
        articles=[],
        articles_total=0,
        tweets=[],
        tweets_total=0,
        cves=[],
        cves_total=0,
        ioc_by_type={},
        new_tas=[],
        new_tas_total=0,
        campaigns=[],
    )
    return svc.WeeklyInputs(**{**base, **over})  # type: ignore[arg-type]


def test_counts_are_the_true_totals_not_the_length_of_the_trimmed_lists() -> None:
    cves = [NS(cve_id=f"CVE-2026-{n:04d}") for n in range(3)]
    inputs = _inputs(
        articles=[(_article(1), 0)],
        articles_total=412,
        tweets=[NS()],
        tweets_total=318,
        cves=cves,
        cves_total=57,
        ioc_by_type={"ip": 700, "domain": 504},
        new_tas=[NS()],
        new_tas_total=4,
        campaigns=[{"size": 3}] * 14,
    )

    assert inputs.counts == {
        "articles": 412,
        "tweets": 318,
        "iocs": 1204,
        "cves": 57,
        "campaigns": 14,
        "new_threat_actors": 4,
    }


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({}, False),
        ({"ioc_by_type": {"ip": 900}, "new_tas_total": 12}, False),  # IOC/TA saja bukan aktivitas
        ({"articles_total": 1}, True),
        ({"tweets_total": 1}, True),
        ({"cves_total": 1}, True),
    ],
)
def test_a_week_has_activity_only_with_articles_tweets_or_cves(
    over: dict[str, object], expected: bool
) -> None:
    assert _inputs(**over).has_activity is expected


def _tweet(n: int) -> NS:
    return NS(
        author_username=f"u{n}",
        text=f"tweet {n}",
        confirmed_incident=n == 1,
        scan_results={"apac_indicator": True} if n == 1 else {},
    )


def _cve(n: int, **f: object) -> NS:
    return NS(
        cve_id=f"CVE-2026-{n:04d}",
        cve_score=f.get("cve_score"),
        cve_severity=None,
        tech=None,
        cisa_kev=bool(f.get("cisa_kev")),
        poc_available=False,
        summary="a bug",
    )


def test_weekly_prompt_states_the_window_and_exact_totals_next_to_the_trimmed_lists() -> None:
    inputs = _inputs(
        articles=[(_article(1), 7), (_article(2), 0)],
        articles_total=412,
        tweets=[_tweet(1), _tweet(2)],
        tweets_total=318,
        cves=[_cve(1, cisa_kev=True, cve_score=9.8)],
        cves_total=57,
        ioc_by_type={"domain": 5, "ip": 700},
        new_tas=[NS(name="Apt41", source="mitre")],
        new_tas_total=4,
        campaigns=[{"theme": "Apt41 wave", "size": 7, "threat_actors": ["Apt41"]}],
    )

    msg = svc._build_weekly_prompt(inputs).user_message

    assert "2026-09-28 (Monday) to 2026-10-04 (Sunday), UTC calendar dates" in msg
    assert "POSTED 2026-09-28..2026-10-04 (412 total, 2 story lines shown;" in msg
    assert "X / TWITTER POSTS 2026-09-28..2026-10-04 (318 total, 2 strongest shown)" in msg
    assert "NEW / UPDATED CVES 2026-09-28..2026-10-04 (57 total, 1 strongest shown;" in msg
    assert "NEW IOCS 2026-09-28..2026-10-04 (705 total)" in msg
    assert "ip=700, domain=5" in msg  # per tipe, terbanyak dulu
    assert "(4 total, 1 first shown)" in msg
    assert "- [#1] [CISA] story 1 | cluster: 7 articles" in msg
    assert "- [#2] [CISA] story 2\n" in msg  # bukan anggota klaster: tanpa akhiran
    assert "- @u1 [CONFIRMED-INCIDENT APAC]: tweet 1" in msg
    assert "- CVE-2026-0001 (CVSS 9.8, KEV): a bug" in msg
    assert "- Apt41 wave — 7 articles | actors: Apt41" in msg


def test_weekly_prompt_prints_no_total_suffix_when_nothing_was_trimmed() -> None:
    msg = svc._build_weekly_prompt(
        _inputs(articles=[(_article(1), 0)], articles_total=1, cves=[_cve(1)], cves_total=1)
    ).user_message

    assert "POSTED 2026-09-28..2026-10-04 (1 total;" in msg
    assert "NEW / UPDATED CVES 2026-09-28..2026-10-04 (1 total;" in msg


def test_weekly_prompt_marks_empty_sections_and_caps_the_campaign_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "_WEEKLY_MAX_CAMPAIGNS", 2)
    campaigns = [{"theme": f"Camp {i}", "size": 3 + i, "threat_actors": []} for i in range(5)]

    msg = svc._build_weekly_prompt(_inputs(campaigns=campaigns)).user_message

    assert msg.count("  (none)") == 4  # artikel, tweet, CVE, threat actor
    assert "NEW IOCS 2026-09-28..2026-10-04 (0 total) ==\nnone" in msg
    assert "(5 total, 2 most severe shown;" in msg
    assert "- Camp 1 — 4 articles" in msg and "Camp 2" not in msg


def test_prompt_items_count_what_actually_went_into_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "_WEEKLY_MAX_CAMPAIGNS", 2)
    inputs = _inputs(
        articles=[(_article(1), 0)] * 3,
        articles_total=400,
        tweets=[NS()] * 2,
        tweets_total=90,
        cves=[NS()],
        cves_total=30,
        ioc_by_type={"ip": 9},
        new_tas=[NS()] * 4,
        new_tas_total=60,
        campaigns=[{}] * 5,
    )

    items = svc._weekly_prompt_items(inputs)

    assert items == {
        "articles": 3,
        "tweets": 2,
        "cves": 1,
        "iocs": 9,
        "campaigns": 2,
        "new_threat_actors": 4,
    }
    assert set(items) == set(inputs.counts)  # kunci sama dengan `counts` dan dengan recap harian


# --- prompt sistem dan hasil "tidak ada aktivitas" ---------------------------------------------


def test_weekly_system_prompt_is_a_weekly_brief_with_a_one_to_two_week_forecast() -> None:
    prompt = svc.WEEKLY_SYSTEM_PROMPT

    assert "weekly desk-brief" in prompt
    assert "next 1-2 weeks" in prompt
    assert "yesterday" not in prompt.lower() and "1-3 days" not in prompt
    stories, tweets = svc._WEEKLY_MAX_TOP_STORIES, svc._WEEKLY_MAX_TOP_TWEETS
    assert (
        f"top_stories to <={stories}, top_tweets to <={tweets},"
        f" likely_events to <={svc._WEEKLY_MAX_LIKELY_EVENTS}"
    ) in prompt


def test_the_daily_system_prompt_is_untouched_by_the_weekly_one() -> None:
    assert "daily desk-brief" in svc.SYSTEM_PROMPT
    assert "next 1-3 days" in svc.SYSTEM_PROMPT
    assert svc.SYSTEM_PROMPT is not svc.WEEKLY_SYSTEM_PROMPT


def test_no_activity_result_has_the_shape_of_a_model_reply_with_empty_lists() -> None:
    result = svc._no_activity_result(D(2026, 9, 28), D(2026, 10, 4))

    assert result["headline"] == "No notable cyber activity this week."
    assert "2026-09-28 and 2026-10-04" in result["recap"]["summary"]
    for key in (
        "top_stories",
        "top_tweets",
        "active_threat_actors",
        "new_threat_actors_added",
        "notable_cves",
        "active_campaigns",
        "apac_signals",
    ):
        assert result["recap"][key] == []
    assert result["forecast"]["likely_events"] == []
    assert result["forecast"]["watch_items"] == []


# --- PR 3: prompt harian tidak berubah ---------------------------------------------------------


def test_the_daily_prompt_is_untouched_by_the_weekly_quality_work() -> None:
    """Perubahan PR 3 (id artikel, seksi review, `article_id`) hanya untuk jalur MINGGUAN: prompt
    harian tetap sama byte per byte. Kalau test ini gagal, yang berubah prompt harian; ubahlah
    hash/literalnya hanya kalau itu memang keputusan, bukan efek samping."""
    article = NS(
        id=7,
        title="Apt41 exploits a VPN zero-day",
        source="CISA",
        url="https://x/7",
        threat_actors=[NS(threat_actor="Apt41"), NS(threat_actor="Lazarus")],
    )
    tweet = NS(
        author_username="u",
        text="CVE-2026-1 is being exploited",
        confirmed_incident=True,
        scan_results={
            "apac_indicator": True,
            "cve_list": ["CVE-2026-1"],
            "mentioned_group": ["Apt41"],
        },
    )
    cve = NS(
        cve_id="CVE-2026-0001",
        cve_score=9.8,
        cve_severity="CRITICAL",
        tech="nginx",
        cisa_kev=True,
        poc_available=True,
        summary="A short bug summary",
    )
    campaign = {"theme": "Apt41 wave", "size": 3, "threat_actors": ["Apt41"], "article_ids": [7]}

    msg = svc._build_user_message(
        "2026-03-02",
        [article],
        [tweet],
        [NS(type="ip"), NS(type="ip")],
        [cve],
        [campaign],
        [NS(name="Apt41", source="mitre")],
    )

    assert msg == "\n".join(
        [
            "DAILY RECAP TARGET DATE: 2026-03-02 (UTC)",
            "",
            "== NEWS ROOM ARTICLES POSTED 2026-03-02 (1 total) ==",
            "- [CISA] Apt41 exploits a VPN zero-day | actors: Apt41, Lazarus",
            "",
            "== X / TWITTER POSTS ON 2026-03-02 (1 cyber-relevant) ==",
            "- @u [CONFIRMED-INCIDENT APAC]: CVE-2026-1 is being exploited | groups: Apt41"
            " | CVEs: CVE-2026-1",
            "",
            "== NEW / UPDATED CVES ON 2026-03-02 (1 total) ==",
            "- CVE-2026-0001 (CVSS 9.8, CRITICAL, tech: nginx, KEV, PoC): A short bug summary",
            "",
            "== NEW IOCS ON 2026-03-02 (2 total) ==",
            "ip=2",
            "",
            "== NEW THREAT ACTORS ADDED TO DATABASE ON 2026-03-02 (1 total) ==",
            "- Apt41 (source: mitre)",
            "",
            "== ACTIVE CAMPAIGN CLUSTERS (last 7d, momentum context for forecast) ==",
            "- Apt41 wave \u2014 3 articles | actors: Apt41",
            "",
            "Now produce the JSON recap+forecast per the schema. Remember: forecast must cite"
            " concrete signals from above.",
            "",
        ]
    )
    assert (
        hashlib.sha256(svc.SYSTEM_PROMPT.encode()).hexdigest()
        == "ac75917cd03a279ef2261e1e3a7e30bf7ae6a1f83d1a20ba51fbb4a1cc860ea0"
    )


def test_an_article_line_has_an_id_only_when_asked_so_the_daily_line_stays_as_it_was() -> None:
    article = _article(12)

    assert svc._article_line(article) == "- [CISA] story 12"
    assert svc._article_line(article, with_id=True) == "- [#12] [CISA] story 12"


# --- PR 3: prompt mingguan -----------------------------------------------------------------------


def test_weekly_system_prompt_asks_for_article_ids_verbatim_names_and_a_forecast_review() -> None:
    prompt = svc.WEEKLY_SYSTEM_PROMPT

    assert '"article_id": <int, the number in the [#id] marker' in prompt
    assert '"forecast_review": [' in prompt
    assert '"verdict": "happened|partly|not_happened|unclear"' in prompt
    assert "A story without a valid article_id is discarded." in prompt
    assert "Copy CVE IDs, threat actor names and campaign themes exactly" in prompt
    assert 'If the input has a "LAST WEEK\'S FORECAST" section' in prompt
    assert "yesterday" not in prompt.lower()  # tetap prompt MINGGUAN


def _printed_week() -> svc.WeeklyInputs:
    """Satu pekan dengan item yang tercetak dan yang tidak (actor keempat artikel, kampanye di luar
    batas), supaya `known` bisa dicek untuk KEDUANYA."""
    first = _article(12)
    first.title = "Patch CVE-2026-4444 now"
    first.threat_actors = [NS(threat_actor=n) for n in ("Apt41", "Lazarus", "Sandworm", "Turla")]
    tweet = NS(
        author_username="u",
        text="fin7 is back",
        confirmed_incident=False,
        scan_results={"mentioned_group": ["FIN7"], "cve_list": ["CVE-2026-5555"]},
    )
    return _inputs(
        articles=[(first, 3), (_article(7, source="Vice"), 0)],
        articles_total=2,
        tweets=[tweet],
        tweets_total=1,
        cves=[_cve(1)],
        cves_total=1,
        new_tas=[NS(name="Ghost", source="mitre")],
        new_tas_total=1,
        campaigns=[
            {"theme": "Apt41 wave", "size": 3, "threat_actors": ["Apt41"]},
            {"theme": "Hidden wave", "size": 3, "threat_actors": []},
        ],
    )


def test_every_weekly_article_line_carries_its_id_and_the_prompt_hands_back_the_same_ids() -> None:
    prompt = svc._build_weekly_prompt(_printed_week())

    printed = {
        int(i) for i in re.findall(r"^- \[#(\d+)\]", prompt.user_message, flags=re.MULTILINE)
    }
    assert printed == {12, 7} == set(prompt.known.articles)
    assert prompt.known.articles[12] == grounding.ArticleRef(
        url="https://example.com/story/12", source="CISA"
    )
    assert prompt.known.articles[7].source == "Vice"


def test_the_prompt_hands_back_exactly_what_it_printed_and_nothing_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Himpunan masukan dibangun bersama baris-barisnya: yang tidak tercetak (actor keempat,
    kampanye di luar batas `_WEEKLY_MAX_CAMPAIGNS`) tidak boleh dianggap dikenal, kalau tidak
    pemeriksaan grounding meloloskan karangan yang kebetulan sama dengan yang tidak dikirim."""
    monkeypatch.setattr(svc, "_WEEKLY_MAX_CAMPAIGNS", 1)
    known = svc._build_weekly_prompt(_printed_week()).known
    check = grounding.Grounder(known)

    printed_actors = ["Apt41", "Lazarus", "Sandworm", "FIN7", "Ghost"]  # artikel, tweet, TA baru
    assert check.name_list("a", printed_actors, "threat_actors") == printed_actors
    assert check.name_list("a", ["Turla"], "threat_actors") == []  # [:3] per artikel
    campaigns = [{"theme": "Apt41 wave"}, {"theme": "Hidden wave"}]
    assert check.name_list("c", campaigns, "campaigns", key="theme") == campaigns[:1]
    assert check.name_list("s", ["CISA", "Vice", "Reuters"], "sources") == ["CISA", "Vice"]
    # CVE id dikenali dari seluruh teks: daftar CVE, judul artikel, dan baris tweet.
    printed_cves = ["CVE-2026-0001", "CVE-2026-4444", "CVE-2026-5555"]
    assert check.cve_list("v", [*printed_cves, "CVE-2026-9999"]) == printed_cves


def test_the_review_section_appears_only_when_last_week_has_events() -> None:
    inputs = _inputs()
    events = [
        {
            "id": "f1",
            "event": "ransomware wave",
            "basis": "three hospital hits",
            "confidence": "high",
        },
        {"id": "f2", "event": "VPN exploitation", "basis": "", "confidence": ""},
    ]

    plain = svc._build_weekly_prompt(inputs).user_message
    reviewed = svc._build_weekly_prompt(inputs, events).user_message

    assert "LAST WEEK'S FORECAST" not in plain
    assert svc._build_weekly_prompt(inputs, []).user_message == plain  # tanpa event: tak ada seksi
    assert "== LAST WEEK'S FORECAST (judge each item against this week's input;" in reviewed
    assert "- [f1] ransomware wave | basis: three hospital hits | confidence: high" in reviewed
    assert "- [f2] VPN exploitation | basis: n/a | confidence: n/a" in reviewed
    assert (
        reviewed.index("ACTIVE CAMPAIGN CLUSTERS")
        < reviewed.index("LAST WEEK'S FORECAST")
        < reviewed.index("Now produce the JSON")
    )
    # Selain seksi itu, pesannya sama persis: seksi lain tidak bergeser.
    assert (
        reviewed.replace(reviewed[reviewed.index("\n== LAST WEEK'S") : reviewed.index("\nNow")], "")
        == plain
    )


def test_last_weeks_forecast_text_is_cut_so_it_cannot_inflate_the_prompt() -> None:
    long_event = {"id": "f1", "event": "e" * 500, "basis": "b" * 500, "confidence": "low"}

    msg = svc._build_weekly_prompt(_inputs(), [long_event]).user_message

    line = next(line for line in msg.splitlines() if line.startswith("- [f1]"))
    assert len(line) < 500  # event 200 + basis 240 + tanda


def test_a_cve_named_in_last_weeks_forecast_counts_as_part_of_the_input() -> None:
    """Review menyebut CVE pekan lalu ("tidak ada kabar baru soal CVE-X"): itu ada di masukan, jadi
    bukan karangan."""
    events = [{"id": "f1", "event": "CVE-2026-7777 spreads", "basis": "b", "confidence": "low"}]

    known = svc._build_weekly_prompt(_inputs(), events).known

    assert grounding.Grounder(known).cve_list("f", ["CVE-2026-7777"]) == ["CVE-2026-7777"]


# --- PR 3: grounding atas keluaran model --------------------------------------------------------


def _ground_known() -> grounding.Known:
    return grounding.Known.build(
        text=(
            "- [#12] [CISA] Apt41 exploits CVE-2026-0001 | actors: Apt41\n"
            "- Apt41 wave \u2014 3 articles | actors: Apt41"
        ),
        threat_actors=["Apt41"],
        campaigns=["Apt41 wave"],
        sources=["CISA"],
        articles={12: grounding.ArticleRef(url="https://example.com/12", source="CISA")},
    )


def _model_reply() -> dict[str, Any]:
    return {
        "headline": "Week of CVE-2026-9999 chaos",
        "recap": {
            "summary": "Apt41 used CVE-2026-0001 and CVE-2026-8888.",
            "top_stories": [
                {"article_id": 12, "title": "Paraphrase", "why_it_matters": "w", "source": "CISA"},
                {"article_id": 999, "title": "Invented story", "why_it_matters": "x"},
            ],
            "notable_cves": ["CVE-2026-0001", "CVE-2026-7777"],
            "active_threat_actors": ["Apt41", "Midnight Blizzard"],
            "new_threat_actors_added": [{"name": "Ghost", "source": "mitre"}],
            "active_campaigns": [{"theme": "Apt41 wave"}, {"theme": "Operation ShadowGate"}],
        },
        "forecast": {"summary": "s", "likely_events": [{"event": "e", "basis": "CVE-2026-6666"}]},
        "forecast_review": [{"id": "f1", "verdict": "happened", "evidence": "see CVE-2026-5555"}],
    }


def test_invented_items_leave_the_output_and_every_one_is_listed() -> None:
    reply = _model_reply()

    output, report = svc._ground_weekly(reply, _ground_known())

    recap = output["recap"]
    assert [s["article_id"] for s in recap["top_stories"]] == [12]
    assert recap["top_stories"][0]["url"] == "https://example.com/12"
    assert recap["notable_cves"] == ["CVE-2026-0001"]
    assert recap["active_threat_actors"] == ["Apt41"]
    assert recap["new_threat_actors_added"] == []  # "Ghost" tidak ada di masukan
    assert recap["active_campaigns"] == [{"theme": "Apt41 wave"}]
    assert recap["summary"] == "Apt41 used CVE-2026-0001 and [unverified CVE]."
    assert output["headline"] == "Week of [unverified CVE] chaos"
    assert output["forecast"]["likely_events"][0]["basis"] == "[unverified CVE]"
    assert output["forecast_review"][0]["evidence"] == "see [unverified CVE]"
    assert {(d["field"], d["value"], d["reason"]) for d in report["dropped"]} == {
        ("recap.top_stories", "Invented story [#999]", "unknown_article_id"),
        ("recap.notable_cves", "CVE-2026-7777", "not_in_input"),
        ("recap.active_threat_actors", "Midnight Blizzard", "not_in_input"),
        ("recap.new_threat_actors_added", "Ghost", "not_in_input"),
        ("recap.active_campaigns", "Operation ShadowGate", "not_in_input"),
        ("recap.summary", "CVE-2026-8888", "not_in_input"),
        ("headline", "CVE-2026-9999", "not_in_input"),
        ("forecast.likely_events[0].basis", "CVE-2026-6666", "not_in_input"),
        ("forecast_review[0].evidence", "CVE-2026-5555", "not_in_input"),
    }
    assert report["count"] == len(report["dropped"]) == 9


def test_a_clean_reply_passes_through_with_nothing_listed() -> None:
    reply = {
        "headline": "Quiet",
        "recap": {"summary": "Apt41 used CVE-2026-0001.", "notable_cves": ["CVE-2026-0001"]},
        "forecast": {"summary": "calm"},
    }

    output, report = svc._ground_weekly(reply, _ground_known())

    assert output == reply
    assert report == {"dropped": [], "count": 0}


def test_grounding_does_not_modify_the_parsed_reply_it_is_given() -> None:
    reply = _model_reply()
    before = copy.deepcopy(reply)

    svc._ground_weekly(reply, _ground_known())

    assert reply == before


def test_keys_the_model_did_not_return_are_not_invented_by_the_check() -> None:
    output, report = svc._ground_weekly({"recap": {"summary": "s"}}, _ground_known())

    assert output == {"recap": {"summary": "s"}}
    assert report["count"] == 0


def test_a_reply_that_was_not_json_has_nothing_to_ground() -> None:
    """`_extract_json` mengembalikan `{"_raw": ...}`: teks mentah itu bukan keluaran yang
    ditampilkan (disimpan utuh di `raw_llm`), jadi CVE id di dalamnya tidak dipindai/dicatat."""
    output, report = svc._ground_weekly({"_raw": "oops CVE-2026-9999"}, _ground_known())

    assert output == {}
    assert report == {"dropped": [], "count": 0}


def test_a_top_stories_field_that_is_not_a_list_is_listed_not_crashing() -> None:
    output, report = svc._ground_weekly(
        {"recap": {"top_stories": "one big story"}}, _ground_known()
    )

    assert output["recap"]["top_stories"] == []
    assert [(d["field"], d["reason"]) for d in report["dropped"]] == [
        ("recap.top_stories", "malformed")
    ]
