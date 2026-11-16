"""Unit test skor risiko CVE (rumus murni, tanpa DB)."""

from __future__ import annotations

import pytest
from cti_core.cve_risk import risk_label, risk_score


@pytest.mark.parametrize(
    "cvss,kev,exp,poc,stack,expected",
    [
        (10.0, True, True, True, True, 100.0),
        (9.8, True, False, False, True, 69.4),
        (7.5, False, False, True, False, 32.5),
        (None, False, False, False, True, 20.0),
        (0.0, False, False, False, False, 0.0),
    ],
)
def test_risk_score_matches_priority_formula(
    cvss: float | None, kev: bool, exp: bool, poc: bool, stack: bool, expected: float
) -> None:
    assert risk_score(cvss, kev=kev, exploited=exp, poc=poc, in_stack=stack) == expected


def test_risk_label_thresholds() -> None:
    assert [risk_label(s) for s in (80, 79.9, 60, 59.9, 40, 39.9)] == [
        "critical_patch",
        "high_priority",
        "high_priority",
        "medium",
        "medium",
        "low",
    ]
