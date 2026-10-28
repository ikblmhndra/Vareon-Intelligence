"""Unit test `cti_core.confidence.suggest_grade` (P6 spec 5.3): saran grade sumber dari data 30
hari. Fungsi murni, tanpa DB."""

from __future__ import annotations

from cti_core.confidence import GradeSuggestion, SourceStats, suggest_grade


def _stats(**kw: int) -> SourceStats:
    base = {
        "articles": 20,
        "rejected": 0,
        "artefact_articles": 10,
        "multi_source_stories": 0,
        "lead_count": 0,
        "ioc_verdicts": 0,
        "ioc_fp": 0,
    }
    base.update(kw)
    return SourceStats(**base)


def test_percentages() -> None:
    s = _stats(articles=16, rejected=9, artefact_articles=4, ioc_verdicts=5, ioc_fp=1)
    assert round(s.rejected_pct, 2) == 36.0
    assert s.artefact_pct == 25.0
    assert s.ioc_fp_pct == 20.0


def test_percentages_zero_denominators() -> None:
    s = _stats(articles=0, rejected=0, artefact_articles=0)
    assert (s.rejected_pct, s.artefact_pct, s.ioc_fp_pct) == (0.0, 0.0, 0.0)


def test_off_topic_lowers_one_grade() -> None:
    s = _stats(articles=16, rejected=9, artefact_articles=0)
    assert suggest_grade("B", s) == GradeSuggestion("C", ["off_topic"])


def test_off_topic_with_artefacts_keeps() -> None:
    s = _stats(articles=16, rejected=9, artefact_articles=5)
    assert suggest_grade("B", s) is None


def test_reports_first_raises_c_to_b() -> None:
    s = _stats(multi_source_stories=34, lead_count=19)
    assert suggest_grade("C", s) == GradeSuggestion("B", ["reports_first"])


def test_reports_first_never_suggests_a() -> None:
    s = _stats(multi_source_stories=34, lead_count=19)
    assert suggest_grade("B", s) is None


def test_reports_first_needs_enough_stories() -> None:
    s = _stats(multi_source_stories=4, lead_count=4)
    assert suggest_grade("C", s) is None


def test_too_few_articles() -> None:
    s = _stats(articles=9, rejected=9, artefact_articles=0)
    assert suggest_grade("B", s) is None


def test_e_source_not_lowered() -> None:
    s = _stats(articles=16, rejected=9, artefact_articles=0)
    assert suggest_grade("E", s) is None
    assert suggest_grade("F", s) is None


def test_d_lowers_to_e() -> None:
    s = _stats(articles=16, rejected=9, artefact_articles=0)
    assert suggest_grade("d", s) == GradeSuggestion("E", ["off_topic"])


def test_ioc_false_positives_lower() -> None:
    s = _stats(ioc_verdicts=5, ioc_fp=1)
    assert suggest_grade("A", s) == GradeSuggestion("B", ["ioc_false_positives"])


def test_ioc_rule_needs_enough_verdicts() -> None:
    s = _stats(ioc_verdicts=4, ioc_fp=4)
    assert suggest_grade("B", s) is None


def test_lowering_wins_over_raising() -> None:
    s = _stats(articles=16, rejected=9, artefact_articles=0, multi_source_stories=34, lead_count=19)
    assert suggest_grade("C", s) == GradeSuggestion("D", ["off_topic"])
