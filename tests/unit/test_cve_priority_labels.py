"""Unit test fungsi murni `cti_api.services.cve_priority` (gak butuh
DB). Fase 7.4 Grup A."""

from __future__ import annotations

from cti_api.services import cve_priority as svc
from cti_core.cve_risk import risk_label


def test_priority_label_thresholds() -> None:
    assert svc._priority_label(85) == "critical_patch"
    assert svc._priority_label(65) == "high_priority"
    assert svc._priority_label(45) == "medium"
    assert svc._priority_label(10) == "low"
    assert svc._priority_label is risk_label


def test_patch_urgency_critical_in_tech_stack_is_immediate() -> None:
    assert svc._patch_urgency("critical_patch", True) == "immediate"


def test_patch_urgency_critical_not_in_tech_stack_is_24h() -> None:
    assert svc._patch_urgency("critical_patch", False) == "24h"


def test_patch_urgency_high_priority_is_7d() -> None:
    assert svc._patch_urgency("high_priority", False) == "7d"


def test_patch_urgency_medium_is_30d() -> None:
    assert svc._patch_urgency("medium", False) == "30d"


def test_patch_urgency_low_is_monitor() -> None:
    assert svc._patch_urgency("low", False) == "monitor"
