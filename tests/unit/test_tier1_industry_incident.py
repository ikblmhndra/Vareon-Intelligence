"""Tes taksonomi industri + aturan insiden tier 1 (murni, tanpa LLM)."""

from __future__ import annotations

import re

from cti_enrich.stages import classify
from cti_enrich.tier1.incident import incident_verdict
from cti_enrich.tier1.industry import INDUSTRY_KEYWORDS, match_industries


def test_industry_keys_match_prompt():
    m = re.search(r'\["Government.*?"General"\]', classify._PROMPT)
    assert m
    names = set(re.findall(r'"([^"]+)"', m.group(0)))
    assert set(INDUSTRY_KEYWORDS) == names - {"General"}
    assert all(len(v) >= 5 for v in INDUSTRY_KEYWORDS.values())


def test_title_hit_counts():
    assert match_industries("Hospital network hit by ransomware", "") == [
        "Healthcare & Life Sciences"
    ]


def test_body_needs_two_hits():
    assert match_industries("Something happened", "The banks were targeted.") == []
    assert match_industries("Something happened", "The banks and a credit union were hit.") == [
        "Finance & Insurance"
    ]


def test_max_three():
    text = (
        "A hospital, banks, a university, an airline and a telecom operator were hit. "
        "The credit union, the school district, the health system, the port authority "
        "and the mobile carrier also reported issues."
    )
    assert len(match_industries("x", text)) == 3


def test_body_beyond_1500_ignored():
    text = "x " * 800 + "banks credit union"
    assert match_industries("x", text) == []


def test_incident_confirmed():
    v = incident_verdict("Acme Corp confirms data breach after ransomware attack", "", None)
    assert v.confirmed is True
    assert any(r.startswith("verb:") for r in v.reasons)


def test_incident_guide_title_not_confirmed():
    v = incident_verdict("How to respond to a data breach", "", "Acme")
    assert v.confirmed is False
    assert any(r.startswith("guide:") for r in v.reasons)


def test_incident_needs_victim():
    assert incident_verdict("Ransomware attacks rise 30%", "", None).confirmed is False


def test_incident_victim_from_llm():
    assert incident_verdict("Hospital systems encrypted", "", "Regional Hospital").confirmed is True


def test_incident_advisory_not_confirmed():
    v = incident_verdict("Acme could be breached via new flaw", "", "Acme")
    assert v.confirmed is False


def test_incident_report_title_not_confirmed():
    v = incident_verdict("Report: Acme Corp hacked in 2025 trends", "", "Acme")
    assert v.confirmed is False
    assert "guide:report:" in v.reasons


import pytest  # noqa: E402


@pytest.mark.parametrize(
    ("title", "text"),
    [
        ("Mandiant says hackers breached many firms", ""),
        ("Microsoft reports surge in leaked credentials", ""),
        ("Google reports Chrome zero-day", "A leaked exploit code was seen."),
        ("Patch Tuesday fixes 80 flaws", "Microsoft says attackers hacked into servers."),
    ],
)
def test_vendor_reports_not_victim(title, text):
    assert incident_verdict(title, text, None).confirmed is False


def test_confirms_ransomware_attack():
    assert incident_verdict("Acme Corp confirms ransomware attack", "", None).confirmed is True


def test_reasons_readable():
    v = incident_verdict("Acme Corp confirms ransomware attack", "", None)
    assert all("\\" not in r and "(" not in r for r in v.reasons)
    g = incident_verdict("How to respond to a breach", "", "Acme")
    assert "guide:how to" in g.reasons


def test_may_month_not_guide():
    assert incident_verdict("Acme hacked in May", "", "Acme").confirmed is True
    assert incident_verdict("Acme may have been hacked", "", "Acme").confirmed is False


@pytest.mark.parametrize(
    "title",
    [
        "Crypto mining malware hits Docker",
        "Click farm operators arrested",
        "Android factory reset bypass",
        "Software supply chain attack on npm",
        "Government agencies urged to patch",
        "SCADA flaw found",
        "Cloud provider outage",
    ],
)
def test_noisy_terms_no_industry(title):
    assert match_industries(title, "") == []
