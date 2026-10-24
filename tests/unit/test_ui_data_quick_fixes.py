"""Quick fix audit UI 2026-10-24 (`docs/UI_DATA_AUDIT.md`): bagian yang murni fungsi."""

from __future__ import annotations

import datetime

import httpx
import pytest
from cti_api.services.dashboard_overview import build_brief
from cti_api.services.recap import RecapEmptyError, _ensure_not_empty
from cti_api.services.trending import TrendItem
from cti_enrich.stages.score import compile_name_patterns, match_names
from cti_enrich.stages.title import normalize_title
from cti_scraper.families.rss import _parse_feed_date
from cti_scrapers.feeds.hackernews import Hackernews
from cti_scrapers.feeds.toxinlabs import ToxinLabs

from tests.unit.scraper_helpers import NOW, make_ctx

# ── U10: tanggal dari feed, bukan waktu scrape ──────────────────────────────

_ATOM = (
    b'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
    b"<entry><title>Old post</title>"
    b'<link href="https://example.com/old" rel="alternate" />'
    b"<published>2020-04-02T10:00:00+00:00</published></entry>"
    b"</feed>"
)


def _rss(pub_date: str) -> bytes:
    return (
        "<rss><channel><item><title>T</title><link>https://example.com/a</link>"
        f"<pubDate>{pub_date}</pubDate></item></channel></rss>"
    ).encode()


def test_atom_scraper_uses_published_date() -> None:
    ctx = make_ctx(ToxinLabs, lambda r: httpx.Response(200, content=_ATOM))
    [item] = list(ToxinLabs().fetch(ctx))
    assert item.posted_on == datetime.date(2020, 4, 2)


def test_rss_scraper_uses_pub_date() -> None:
    feed = _rss("Thu, 02 Apr 2020 10:00:00 GMT")
    ctx = make_ctx(Hackernews, lambda r: httpx.Response(200, content=feed))
    [item] = list(Hackernews().fetch(ctx))
    assert item.posted_on == datetime.date(2020, 4, 2)


def test_future_pub_date_is_clamped_to_today() -> None:
    feed = _rss("Mon, 01 Jan 2035 00:00:00 GMT")
    ctx = make_ctx(Hackernews, lambda r: httpx.Response(200, content=feed))
    [item] = list(Hackernews().fetch(ctx))
    assert item.posted_on == NOW.date()


def test_explicit_none_keeps_scrape_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Hackernews, "date_path", None)
    feed = _rss("Thu, 02 Apr 2020 10:00:00 GMT")
    ctx = make_ctx(Hackernews, lambda r: httpx.Response(200, content=feed))
    [item] = list(Hackernews().fetch(ctx))
    assert item.posted_on == NOW.date()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Thu, 02 Apr 2020 10:00:00 GMT", datetime.date(2020, 4, 2)),
        ("2020-04-02T10:00:00Z", datetime.date(2020, 4, 2)),
        ("2020-04-02", datetime.date(2020, 4, 2)),
        ("not a date", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_feed_date(text: str | None, expected: datetime.date | None) -> None:
    assert _parse_feed_date(text) == expected


# ── U8: Cobalt Strike bukan aktor ───────────────────────────────────────────


def test_software_name_does_not_leak_into_shorter_actor_name() -> None:
    groups = compile_name_patterns(["Cobalt", "Akira"])
    mask = compile_name_patterns(["cobalt strike"])
    text = "Akira affiliates dropped Cobalt Strike beacons"
    assert match_names(groups, text, mask=mask) == ["Akira"]
    assert match_names(groups, "The Cobalt group returned", mask=mask) == ["Cobalt"]


def test_longest_actor_name_wins() -> None:
    groups = compile_name_patterns(["Lazarus", "Lazarus Group", "Kimsuky"])
    assert match_names(groups, "Lazarus Group and Kimsuky") == ["Lazarus Group", "Kimsuky"]
    assert match_names(groups, "Lazarus Group, later Lazarus again") == ["Lazarus", "Lazarus Group"]


# ── U27: judul ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Marvell, Microsoft &amp; Oracle Work", "Marvell, Microsoft & Oracle Work"),
        ("SWIFT &amp;amp; Middleware", "SWIFT & Middleware"),
        (
            "2026-10-21-phishing-pages-hosted-on-AI-based-site-builders.txt",
            "Phishing pages hosted on AI based site builders",
        ),
        ("2026-09-28-AgtaBackup-RAT-Campaign.txt", "AgtaBackup RAT Campaign"),
        ("  Normal   title  ", "Normal title"),
        ("Release notes for v1.2.txt support", "Release notes for v1.2.txt support"),
    ],
)
def test_normalize_title(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


def test_normalize_title_decodes_numeric_entities() -> None:
    quote_open, apostrophe, quote_close = chr(0x201C), chr(0x2019), chr(0x201D)
    assert (
        normalize_title("&#8220;Don&#8217;t&#8221;") == f"{quote_open}Don{apostrophe}t{quote_close}"
    )


# ── U4: brief tanpa pembanding yang layak ───────────────────────────────────


def test_brief_without_reliable_baseline_says_most_frequent() -> None:
    t = TrendItem(
        kind="ttp",
        name="Exploit Public-Facing Application",
        ttp_id="T1190",
        count=129,
        prev_count=1,
        change_pct=None,
        is_new=False,
        daily=[],
    )
    b = build_brief(
        top_trend=t,
        trend_reliable=False,
        kev_in_stack=0,
        incidents=0,
        prev_incidents=None,
        drivers=[],
    )
    assert (
        b["headline"]
        == "T1190 Exploit Public-Facing Application paling sering muncul pada periode ini."
    )


# ── U13: recap kosong ───────────────────────────────────────────────────────


def test_empty_parsed_recap_is_refused() -> None:
    with pytest.raises(RecapEmptyError):
        _ensure_not_empty(
            {"headline": " ", "recap": {}}, kind="weekly", period="2026-10-12", model="m"
        )


@pytest.mark.parametrize(
    "output",
    [{"_raw": "not json"}, {"headline": "Quiet week"}, {"headline": "", "recap": {"summary": "x"}}],
)
def test_unreadable_or_filled_recap_is_kept(output: dict[str, object]) -> None:
    _ensure_not_empty(output, kind="weekly", period="2026-10-12", model="m")
