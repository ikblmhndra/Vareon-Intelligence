"""Model skor P6: kredibilitas (tangga aturan), confidence, dan prioritas (fungsi murni)."""

from __future__ import annotations

from typing import Any

from cti_core.confidence import ArticleFacts, assess


def _facts(**kw: Any) -> ArticleFacts:
    base: dict[str, Any] = {
        "reliability_grade": "B",
        "content_kind": "vendor_research",
        "story_source_count": 1,
        "has_cve": False,
        "has_ioc": False,
        "explicit_ttp_count": 0,
        "bonus_ttp_count": 0,
        "has_actor": False,
        "confirmed_incident": False,
        "kev": False,
        "poc": False,
    }
    base.update(kw)
    return ArticleFacts(**base)


def test_ungraded_source_is_f6():
    a = assess(_facts(reliability_grade=None))
    assert (a.reliability_grade, a.credibility, a.confidence_score) == ("F", 6, 50)
    assert a.reasons["credibility"] == ["ungraded"]


def test_kev_source_is_official():
    a = assess(_facts(reliability_grade="A", content_kind="kev"))
    assert a.credibility == 1
    assert a.reasons["credibility"] == ["official"]


def test_three_sources_with_artefact_is_1_two_is_2():
    assert assess(_facts(content_kind="news", story_source_count=3, has_ioc=True)).credibility == 1
    assert assess(_facts(content_kind="news", story_source_count=2, has_ioc=True)).credibility == 2
    assert assess(_facts(content_kind="news", story_source_count=3)).credibility == 3


def test_primary_with_artefact_is_2_without_is_3():
    assert assess(_facts(has_cve=True)).credibility == 2
    assert assess(_facts()).credibility == 3


def test_llm_ttp_is_not_an_artefact():
    assert assess(_facts(content_kind="news", bonus_ttp_count=4)).credibility == 4
    assert (
        assess(_facts(content_kind="news", explicit_ttp_count=1, bonus_ttp_count=1)).credibility
        == 3
    )


def test_single_aggregator_without_artefact_is_4():
    a = assess(_facts(reliability_grade="C", content_kind="news"))
    assert (a.admiralty_code, a.confidence_score, a.reasons["credibility"]) == (
        "C4",
        40,
        ["single_aggregator"],
    )


def test_unknown_content_kind_is_not_primary():
    assert assess(_facts(content_kind=None)).credibility == 4


def test_credibility_override_wins_including_5():
    a = assess(_facts(credibility_override=5, has_cve=True))
    assert (a.credibility, a.confidence_score, a.reasons["credibility"]) == (5, 40, ["analyst"])


def test_confidence_override_keeps_credibility_and_feeds_priority():
    a = assess(_facts(confidence_override=95, confirmed_incident=True))
    assert (a.credibility, a.confidence_score, a.priority_score) == (3, 95, 120)


def test_confidence_scale():  # B=70, 2=70 / C=50, 1=90
    assert assess(_facts(has_cve=True)).confidence_score == 70
    c = assess(
        _facts(reliability_grade="C", content_kind="news", story_source_count=3, has_cve=True)
    )
    assert c.confidence_score == 70


def test_priority_points_and_caps():
    a = assess(
        _facts(
            confirmed_incident=True,
            kev=True,
            poc=True,
            bonus_ttp_count=9,
            has_actor=True,
            story_source_count=12,
            has_cve=True,
        )
    )
    # conf B1 = 80; +25 +15 (poc diabaikan bila kev) +12 +8 +16
    assert a.priority_score == 156
    assert [p["code"] for p in a.reasons["priority"]] == [
        "confirmed_incident",
        "corroboration",
        "kev",
        "ttps",
        "actor",
    ]


def test_poc_without_kev_is_8():
    assert assess(_facts(poc=True)).priority_score == 68  # B3 = (70 + 50) / 2 = 60, + 8


def test_artefact_reason_codes():
    r = assess(_facts(has_cve=True, has_ioc=True, explicit_ttp_count=1)).reasons
    assert r["credibility"] == ["primary", "cve", "ioc", "explicit_ttp"]


def test_row3_emits_all_applicable_codes():
    r = assess(_facts(story_source_count=2)).reasons
    assert r["credibility"] == ["primary", "corroborated_2"]
    r = assess(_facts(content_kind="news", has_ioc=True)).reasons
    assert r["credibility"] == ["ioc"]


def test_three_sources_reason_codes():
    r = assess(_facts(content_kind="news", story_source_count=3, has_cve=True)).reasons
    assert r["credibility"] == ["corroborated_3", "cve"]
