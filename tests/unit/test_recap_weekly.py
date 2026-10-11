"""Unit test logika murni recap MINGGUAN (`cti_api.services.recap`, #21 PR 2) -- tanpa DB, tanpa
LLM: jendela Senin-Minggu, penolakan pekan yang belum selesai, penyusun agregat/prompt, dan hasil
"tidak ada aktivitas". Yang butuh Postgres (kolektor, cache, migrasi) ada di
`tests/integration/test_recap_service.py`."""

from __future__ import annotations

import datetime
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
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

    msg = svc._build_weekly_user_message(inputs)

    assert "2026-09-28 (Monday) to 2026-10-04 (Sunday), UTC calendar dates" in msg
    assert "POSTED 2026-09-28..2026-10-04 (412 total, 2 story lines shown;" in msg
    assert "X / TWITTER POSTS 2026-09-28..2026-10-04 (318 total, 2 strongest shown)" in msg
    assert "NEW / UPDATED CVES 2026-09-28..2026-10-04 (57 total, 1 strongest shown;" in msg
    assert "NEW IOCS 2026-09-28..2026-10-04 (705 total)" in msg
    assert "ip=700, domain=5" in msg  # per tipe, terbanyak dulu
    assert "(4 total, 1 first shown)" in msg
    assert "- [CISA] story 1 | cluster: 7 articles" in msg
    assert "- [CISA] story 2\n" in msg  # bukan anggota klaster: tanpa akhiran
    assert "- @u1 [CONFIRMED-INCIDENT APAC]: tweet 1" in msg
    assert "- CVE-2026-0001 (CVSS 9.8, KEV): a bug" in msg
    assert "- Apt41 wave — 7 articles | actors: Apt41" in msg


def test_weekly_prompt_prints_no_total_suffix_when_nothing_was_trimmed() -> None:
    msg = svc._build_weekly_user_message(
        _inputs(articles=[(_article(1), 0)], articles_total=1, cves=[_cve(1)], cves_total=1)
    )

    assert "POSTED 2026-09-28..2026-10-04 (1 total;" in msg
    assert "NEW / UPDATED CVES 2026-09-28..2026-10-04 (1 total;" in msg


def test_weekly_prompt_marks_empty_sections_and_caps_the_campaign_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "_WEEKLY_MAX_CAMPAIGNS", 2)
    campaigns = [{"theme": f"Camp {i}", "size": 3 + i, "threat_actors": []} for i in range(5)]

    msg = svc._build_weekly_user_message(_inputs(campaigns=campaigns))

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
