"""Unit test `cti_api.services.newsletter_ranking` -- fungsi murni, tanpa DB (ROADMAP #22, PR 7).

Kandidat dibuat tangan. Judulnya SENGAJA unik per artikel (token `headline0001 story0001`, tanpa
kata bersama): dedup menyatukan judul yang mirip, jadi judul serupa ("Story 1", "Story 2") akan
runtuh jadi satu dan merusak test yang bukan tentang dedup.
"""

from __future__ import annotations

import datetime
import json
from collections import Counter
from typing import Any, get_args

import pytest
from cti_api.schemas.newsletter import (
    MAX_COMPACT_PER_SECTION,
    MAX_FULL_PER_SECTION,
    MAX_HIGHLIGHTS,
    SectionName,
    TierName,
)
from cti_api.services import newsletter_ranking as ranking
from cti_api.services.newsletter_edition import SECTIONS
from cti_api.services.newsletter_ranking import Candidate, RankedArticle, rank_candidates

D = datetime.date


def _c(article_id: int, **kwargs: Any) -> Candidate:
    kwargs.setdefault("title", f"headline{article_id:04d} story{article_id:04d}")
    return Candidate(article_id=article_id, **kwargs)


def _codes(ranked: RankedArticle) -> list[str]:
    return [r.code for r in ranked.reasons]


def _ids(ranked: list[RankedArticle]) -> list[int]:
    return [r.article_id for r in ranked]


# ── Setiap sinyal mengubah urutan ───────────────────────────────────────────────────────────────

_CONTEXT: dict[str, Any] = {"client_countries": ("FR",), "monitored_techs": ("Fortinet",)}

_SIGNALS = [
    ("kev", {"kev_cves": ("CVE-2026-1111",)}, True),
    ("poc", {"poc_cves": ("CVE-2026-2222",)}, True),
    ("confirmed_incident", {"confirmed_incident": True}, True),
    ("monitored_tech", {"title": "Fortinet appliances are being probed"}, True),
    ("client_country", {"victim_countries": ("FR",)}, True),
    ("indonesia", {"victim_countries": ("ID",)}, True),
    ("apac", {"victim_countries": ("JP",)}, True),
    ("coverage", {"cluster_size": 4}, True),
    ("source", {"source": "CISA"}, True),
    ("confidence", {"confidence_score": 100}, False),
]


@pytest.mark.parametrize(("code", "extra", "absent_from_baseline"), _SIGNALS)
def test_each_signal_moves_an_article_above_an_otherwise_equal_one(
    code: str, extra: dict[str, Any], absent_from_baseline: bool
) -> None:
    """Pembanding lebih baru dan ber-id lebih kecil, jadi tanpa sinyal ia yang menang urutan; kalau
    artikel bersinyal naik, itu karena sinyalnya, bukan karena pemecah seri."""
    baseline = _c(1, posted_on=D(2026, 10, 20), confidence_score=60)
    signalled = _c(2, posted_on=D(2026, 10, 5), **{"confidence_score": 60, **extra})

    ranked = rank_candidates([baseline, signalled], **_CONTEXT)

    assert _ids(ranked) == [2, 1]
    assert ranked[0].score > ranked[1].score
    assert code in _codes(ranked[0])
    if absent_from_baseline:
        assert code not in _codes(ranked[1])


def test_without_the_signals_the_tie_break_puts_the_baseline_first() -> None:
    """Kontrol untuk test di atas: dua artikel setara diurutkan terbaru dulu."""
    ranked = rank_candidates(
        [
            _c(2, posted_on=D(2026, 10, 5), confidence_score=60),
            _c(1, posted_on=D(2026, 10, 20), confidence_score=60),
        ]
    )
    assert _ids(ranked) == [1, 2]


# ── Alasan ──────────────────────────────────────────────────────────────────────────────────────


def test_reasons_explain_the_whole_score_and_run_from_largest_to_smallest() -> None:
    candidate = _c(
        1,
        confidence_score=90,
        confirmed_incident=True,
        source="CISA",
        victim_countries=("ID",),
        kev_cves=("CVE-2026-1111",),
        poc_cves=("CVE-2026-1111", "CVE-2026-2222"),
        cluster_size=3,
    )

    (ranked,) = rank_candidates([candidate])

    assert [(r.code, r.points) for r in ranked.reasons] == [
        ("kev", 30),
        ("indonesia", 25),
        ("confirmed_incident", 20),
        ("poc", 10),
        ("confidence", 9),  # (90 - 50) * 12 // 50
        ("source", 8),
        ("coverage", 6),  # (3 - 1) * 3
    ]
    assert sum(r.points for r in ranked.reasons) == ranked.score == 108
    texts = {r.code: r.text for r in ranked.reasons}
    assert texts["kev"] == "Mentions CVE-2026-1111 in the CISA KEV catalog"
    assert texts["poc"] == "A public proof-of-concept exists for CVE-2026-1111, CVE-2026-2222"
    assert texts["indonesia"] == "Indonesia is a victim country"
    assert texts["coverage"] == "Covered by 3 related articles"
    assert texts["source"] == "Source reliability grade A"
    assert texts["confidence"] == "Confidence score 90/100"


def test_a_long_cve_list_is_shortened_in_the_text() -> None:
    cves = tuple(f"CVE-2026-{n}" for n in range(1000, 1005))
    (ranked,) = rank_candidates([_c(1, kev_cves=cves)])
    assert ranked.reasons[0].text == (
        "Mentions CVE-2026-1000, CVE-2026-1001, CVE-2026-1002 (+2 more) in the CISA KEV catalog"
    )


def test_to_item_is_the_stored_shape_and_json_serialisable() -> None:
    (ranked,) = rank_candidates([_c(7, confirmed_incident=True)])

    item = ranked.to_item()

    assert item == {
        "article_id": 7,
        "section": "global_news",
        "tier": "highlight",
        "rank": 1,
        "reasons": [{"code": "confirmed_incident", "text": "Confirmed incident"}],
    }
    assert json.loads(json.dumps(item)) == item


def test_a_candidate_without_any_signal_is_not_suggested() -> None:
    assert rank_candidates([]) == []
    assert rank_candidates([_c(1)]) == []
    assert rank_candidates([_c(1, confidence_score=40, source="Random blog")]) == []


# ── Sinyal satu per satu ────────────────────────────────────────────────────────────────────────


def test_confidence_counts_only_above_the_floor_and_scales_linearly() -> None:
    def points(confidence: int | None) -> int:
        ranked = rank_candidates([_c(1, confidence_score=confidence, confirmed_incident=True)])
        return sum(r.points for r in ranked[0].reasons if r.code == "confidence")

    assert points(None) == 0
    assert points(50) == 0
    assert points(75) == ranking.POINTS_CONFIDENCE_MAX // 2
    assert points(100) == ranking.POINTS_CONFIDENCE_MAX
    assert points(250) == ranking.POINTS_CONFIDENCE_MAX  # nilai di luar 0-100 tidak melonjak


def test_source_grade_uses_the_admiralty_table_and_ignores_unknown_or_empty_sources() -> None:
    def source_codes(source: str) -> list[str]:
        ranked = rank_candidates([_c(1, source=source, confirmed_incident=True)])
        return [r.text for r in ranked[0].reasons if r.code == "source"]

    assert source_codes("CISA") == ["Source reliability grade A"]
    assert source_codes("BleepingComputer") == ["Source reliability grade B"]
    assert source_codes("Wired") == ["Source reliability grade C"]
    assert source_codes("Vice") == []  # D tidak menambah poin
    assert source_codes("Some random blog") == []  # F = tidak bisa dinilai, bukan "buruk"
    # `get_source_reliability("")` mengembalikan "A" (substring kosong cocok ke entri pertama).
    assert source_codes("") == []
    assert source_codes("   ") == []


def test_monitored_tech_uses_the_shared_whole_word_matcher() -> None:
    def hit(title: str, techs: tuple[str, ...]) -> list[str]:
        ranked = rank_candidates(
            [_c(1, title=title, confirmed_incident=True)], monitored_techs=techs
        )
        return [r.text for r in ranked[0].reasons if r.code == "monitored_tech"]

    assert hit("Go compiler flaw lets attackers run code", ("go",)) == [
        "Mentions monitored tech: go"
    ]
    assert hit("Google patches Chrome zero-day", ("go",)) == []  # `go` bukan `google`
    assert hit("Palo Alto Networks firewall bug", ("Palo_Alto-Networks",)) == [
        "Mentions monitored tech: Palo_Alto-Networks"
    ]
    assert hit("Anything about Fortinet", ()) == []  # daftar kosong = tanpa sinyal, bukan "semua"
    assert hit("Fortinet and Cisco flaws", ("Fortinet", "fortinet", "Cisco")) == [
        "Mentions monitored tech: Cisco, Fortinet"
    ]


def test_client_country_is_the_union_over_clients_and_ignores_case() -> None:
    ranked = rank_candidates(
        [_c(1, victim_countries=("sg",), mentioned_countries=("FR", "US"))],
        client_countries=("SG", "fr", "DE"),
    )
    texts = [r.text for r in ranked[0].reasons if r.code == "client_country"]
    assert texts == ["Involves a client country: FR, SG"]


def test_indonesia_victim_outweighs_a_mention_and_both_outweigh_other_apac_countries() -> None:
    def score(**countries: tuple[str, ...]) -> int:
        return rank_candidates([_c(1, **countries)])[0].score

    victim, mentioned = score(victim_countries=("ID",)), score(mentioned_countries=("ID",))
    apac_victim, apac_mentioned = (
        score(victim_countries=("JP",)),
        score(mentioned_countries=("JP",)),
    )
    assert victim > mentioned > apac_victim > apac_mentioned > 0
    assert rank_candidates([_c(1, victim_countries=("US",))]) == []  # negara non-APAC: tanpa sinyal


def test_coverage_grows_with_related_articles_up_to_a_cap() -> None:
    def points(size: int) -> int:
        ranked = rank_candidates([_c(1, cluster_size=size, confirmed_incident=True)])
        return sum(r.points for r in ranked[0].reasons if r.code == "coverage")

    assert points(1) == 0
    assert points(2) == ranking.POINTS_PER_RELATED_ARTICLE
    assert points(4) == 3 * ranking.POINTS_PER_RELATED_ARTICLE
    assert points(500) == ranking.POINTS_COVERAGE_MAX


# ── Section ─────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("victims", "mentioned", "section"),
    [
        ((), ("ID",), "indonesia"),
        (("ID",), (), "indonesia"),
        (("id",), (), "indonesia"),  # kode huruf kecil dinormalkan
        (("JP",), ("ID",), "indonesia"),  # Indonesia mengalahkan APAC
        (("JP",), (), "apac"),
        ((), ("SG", "US"), "apac"),  # satu negara APAC cukup
        (("US",), ("GB",), "global_news"),
        ((), (), "global_news"),
    ],
)
def test_section_is_indonesia_then_apac_then_global(
    victims: tuple[str, ...], mentioned: tuple[str, ...], section: str
) -> None:
    ranked = rank_candidates(
        [_c(1, confidence_score=80, victim_countries=victims, mentioned_countries=mentioned)]
    )
    assert ranked[0].section == section


def test_section_and_tier_names_are_the_ones_the_request_fields_use() -> None:
    assert set(get_args(SectionName)) == set(SECTIONS)
    assert {ranking.SECTION_INDONESIA, ranking.SECTION_APAC, ranking.SECTION_GLOBAL} == set(
        SECTIONS
    )
    assert set(get_args(TierName)) == {"highlight", "full", "compact"}


# ── Tier dan batas ──────────────────────────────────────────────────────────────────────────────


def test_highlights_are_the_top_overall_and_are_not_repeated_in_their_section() -> None:
    # Skor menurun 1 > 2 > 3 > 4 > 5 > 6; section: global, indonesia, apac, global, indonesia, apac.
    candidates = [
        _c(1, kev_cves=("CVE-2026-1",), poc_cves=("CVE-2026-1",), confirmed_incident=True),
        _c(2, victim_countries=("ID",), confirmed_incident=True),
        _c(3, victim_countries=("JP",), kev_cves=("CVE-2026-3",)),
        _c(4, confirmed_incident=True),
        _c(5, mentioned_countries=("ID",)),
        _c(6, mentioned_countries=("JP",)),
    ]

    ranked = rank_candidates(candidates)

    assert _ids(ranked) == [1, 2, 3, 4, 5, 6]
    assert [r.tier for r in ranked] == ["highlight"] * MAX_HIGHLIGHTS + ["full"] * 3
    assert [r.section for r in ranked] == [
        "global_news",
        "indonesia",
        "apac",
        "global_news",
        "indonesia",
        "apac",
    ]  # sebuah highlight tetap membawa section aslinya
    assert len(set(_ids(ranked))) == len(ranked)


def test_ranks_are_contiguous_and_follow_the_score() -> None:
    ranked = rank_candidates(
        [_c(n, confidence_score=100 - n, victim_countries=("ID",)) for n in range(1, 30)]
    )
    assert [r.rank for r in ranked] == list(range(1, len(ranked) + 1))
    scores = [r.score for r in ranked]
    assert scores == sorted(scores, reverse=True)
    assert [r.tier for r in ranked[:MAX_HIGHLIGHTS]] == ["highlight"] * MAX_HIGHLIGHTS


def test_caps_hold_with_far_more_candidates_than_slots() -> None:
    candidates: list[Candidate] = []
    for n in range(40):
        candidates.append(_c(100 + n, victim_countries=("ID",), confidence_score=100))
        candidates.append(_c(200 + n, victim_countries=("JP",), confidence_score=80))
        candidates.append(_c(300 + n, victim_countries=("US",), confidence_score=60))

    ranked = rank_candidates(candidates)

    counts = Counter((r.section, r.tier) for r in ranked)
    assert sum(c for (_, tier), c in counts.items() if tier == "highlight") == MAX_HIGHLIGHTS
    for section in SECTIONS:
        assert counts[(section, "full")] == MAX_FULL_PER_SECTION
        assert counts[(section, "compact")] == MAX_COMPACT_PER_SECTION
    total = MAX_HIGHLIGHTS + len(SECTIONS) * (MAX_FULL_PER_SECTION + MAX_COMPACT_PER_SECTION)
    assert len(ranked) == total
    assert len(set(_ids(ranked))) == total


def test_a_quiet_month_is_not_padded_up_to_the_caps() -> None:
    ranked = rank_candidates([_c(n, confirmed_incident=True) for n in range(1, 6)])
    assert [r.tier for r in ranked] == ["highlight"] * 3 + ["full"] * 2


def test_more_candidates_than_the_dedup_pool_still_respect_the_caps() -> None:
    candidates = [_c(n, confidence_score=60 + n % 40) for n in range(1, ranking.DEDUP_POOL + 60)]
    ranked = rank_candidates(candidates)
    assert len(ranked) == MAX_HIGHLIGHTS + MAX_FULL_PER_SECTION + MAX_COMPACT_PER_SECTION


# ── Urutan pasti ────────────────────────────────────────────────────────────────────────────────


def test_ties_break_by_newest_date_then_lowest_id() -> None:
    ranked = rank_candidates(
        [
            _c(5, posted_on=D(2026, 10, 10), confirmed_incident=True),
            _c(2, posted_on=D(2026, 10, 10), confirmed_incident=True),
            _c(9, posted_on=D(2026, 10, 20), confirmed_incident=True),
            _c(1, posted_on=None, confirmed_incident=True),
        ]
    )
    assert _ids(ranked) == [9, 2, 5, 1]  # tanggal kosong paling akhir


def test_the_result_does_not_depend_on_the_input_order() -> None:
    candidates = [
        _c(n, confidence_score=60 + (n % 4) * 10, posted_on=D(2026, 10, 1 + n % 5))
        for n in range(1, 41)
    ]
    forward = rank_candidates(candidates)
    assert rank_candidates(list(reversed(candidates))) == forward
    assert rank_candidates(candidates[20:] + candidates[:20]) == forward


# ── Duplikat ────────────────────────────────────────────────────────────────────────────────────

_STORY = "Critical Fortinet flaw exploited in the wild by ransomware gang"


def test_duplicate_stories_collapse_into_the_best_scored_one() -> None:
    weak = _c(1, title=_STORY, source="The Hacker News", confidence_score=60)
    strong = _c(2, title=_STORY, source="BleepingComputer", confidence_score=95)
    other = _c(3, confidence_score=70)

    ranked = rank_candidates([weak, other, strong])

    assert sorted(_ids(ranked)) == [2, 3]  # `weak` runtuh ke `strong`, apa pun urutan masukannya
    survivor = next(r for r in ranked if r.article_id == 2)
    assert "coverage" in _codes(survivor)
    assert "Covered by 2 related articles" in [r.text for r in survivor.reasons]


def test_a_duplicate_group_outranks_an_equal_single_story() -> None:
    ranked = rank_candidates(
        [
            _c(1, title=_STORY, source="A", confidence_score=80, posted_on=D(2026, 10, 1)),
            _c(2, title=_STORY, source="B", confidence_score=80, posted_on=D(2026, 10, 1)),
            _c(3, confidence_score=80, posted_on=D(2026, 10, 25)),
        ]
    )
    assert _ids(ranked) == [1, 3]  # 3 lebih baru, tapi liputan 1 lebih luas


def test_the_same_source_repeating_a_title_collapses_without_adding_coverage() -> None:
    """Seri mingguan dari satu sumber bukan tanda cerita yang diliput luas."""
    ranked = rank_candidates(
        [
            _c(1, title=_STORY, source="Weekly Blog", confidence_score=80),
            _c(2, title=_STORY, source="weekly blog", confidence_score=80),
        ]
    )
    assert _ids(ranked) == [1]
    assert "coverage" not in _codes(ranked[0])


def test_a_large_cluster_is_not_shrunk_by_a_smaller_duplicate_group() -> None:
    ranked = rank_candidates(
        [
            _c(1, title=_STORY, source="A", confidence_score=80, cluster_size=6),
            _c(2, title=_STORY, source="B", confidence_score=80, cluster_size=6),
        ]
    )
    assert "Covered by 6 related articles" in [r.text for r in ranked[0].reasons]


def test_distinct_stories_are_never_collapsed() -> None:
    ranked = rank_candidates(
        [
            _c(1, title="Ransomware crew hits hospital group in Jakarta", confirmed_incident=True),
            _c(2, title="Zero-day exploited in a popular browser", confirmed_incident=True),
            _c(
                3,
                title="Quarterly funding round closes for a security startup",
                confidence_score=90,
            ),
        ]
    )
    assert sorted(_ids(ranked)) == [1, 2, 3]
