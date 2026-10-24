"""Grade bawaan per `content_kind` dan rumus skor confidence (0.8.6, spec P2 5.1/5.2)."""

from __future__ import annotations

from cti_core.confidence import DEFAULT_GRADES, compute_score


def test_default_grades_table() -> None:
    assert DEFAULT_GRADES == {
        "kev": ("A", "1"),
        "advisory": ("A", "2"),
        "exploit": ("B", "2"),
        "vendor_research": ("B", "2"),
        "news": ("C", "3"),
        "vendor_marketing": ("C", "4"),
        "social": ("D", "4"),
    }


def test_compute_score_formula_unchanged() -> None:
    assert compute_score("B", "2", 0, 0) == 80
    assert compute_score(None, None, 2, 1) == 70


def test_api_service_reexports_compute_score() -> None:
    from cti_api.services import confidence

    assert confidence.compute_score is compute_score
