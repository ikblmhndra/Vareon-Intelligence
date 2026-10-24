"""Koreksi empat prompt yang membuat platform menyatakan hal yang tidak ada di datanya
(spec 2026-10-24 LLM calls self-healing, bagian 6.1 butir 1-4): ringkasan newsletter dari
metadata, profil threat actor, executive brief, dan email CVE."""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from cti_api.services import cve_email, exec_brief, newsletter, ta_profile

# ── 1. Newsletter: ringkasan dari metadata ───────────────────────────────────


def test_metadata_prompt_forbids_invention() -> None:
    prompt = newsletter._PROMPT_FROM_METADATA
    assert "plausible" not in prompt
    assert "Do not mention that the article was paywalled" not in prompt
    assert "only" in prompt
    assert "do not add" in prompt.lower()


# ── 3. Exec brief ────────────────────────────────────────────────────────────


def test_exec_brief_labels() -> None:
    msg = exec_brief._build_user_message(
        90,
        {
            "total_incidents": 992,
            "confirmed_incident_rate": 37,
            "top_sectors": [],
            "unique_ta_count": 4,
        },
    )
    assert "Threat news articles: 992" in msg
    assert "Confirmed incidents: 367" in msg
    assert "Total incidents tracked" not in msg


def test_exec_brief_prompt_reserves_incident_for_confirmed_count() -> None:
    prompt = exec_brief.SYSTEM_PROMPT
    assert "incident" in prompt
    assert "only for the confirmed" in prompt


# ── 4. CVE email ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("vector", "expected"),
    [
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", "Low"),
        ("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:H", "High"),
        (None, "Unknown"),
        ("", "Unknown"),
    ],
)
def test_cve_computed_attack_complexity(vector: str | None, expected: str) -> None:
    assert cve_email.computed_fields({"cvss_vector": vector})["attack_complexity"] == expected


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        ("CRITICAL", "CRITICAL (24-48h)"),
        ("HIGH", "HIGH (7 days)"),
        ("medium", "MEDIUM (30 days)"),
        ("LOW", "LOW (90 days)"),
        (None, "MEDIUM (30 days)"),
        ("NONE", "MEDIUM (30 days)"),
    ],
)
def test_cve_computed_timeline(severity: str | None, expected: str) -> None:
    assert cve_email.computed_fields({"cve_severity": severity})["recommended_timeline"] == expected


def test_cve_computed_affected_version_and_timestamp() -> None:
    fields = cve_email.computed_fields({"affected": ["foo < 1.2.3", "bar 2.0"]})
    assert fields["affected_version"] == "foo < 1.2.3; bar 2.0"
    assert cve_email.computed_fields({"affected": []})["affected_version"] == "Unknown"
    assert cve_email.computed_fields({})["affected_version"] == "Unknown"

    ts = datetime.datetime.fromisoformat(fields["analysis_timestamp"])
    assert ts.utcoffset() == datetime.timedelta(0)


def _fake_client(content: str) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )
    return client


def test_cve_validator_overwrites_model_values(monkeypatch: pytest.MonkeyPatch) -> None:
    model_out = {
        "summary": "RCE",
        "attack_complexity": "Medium",
        "recommended_timeline": "whenever",
        "affected_version": "all versions",
        "analysis_timestamp": "2020-01-01",
    }
    client = _fake_client(json.dumps(model_out))
    monkeypatch.setattr(cve_email, "get_llm_client", lambda **_: (client, "m"))
    result = cve_email._llm_cve_validator(
        {
            "cve_id": "CVE-2026-0001",
            "cve_severity": "HIGH",
            "cvss_vector": "CVSS:3.1/AV:N/AC:H/PR:N",
            "affected": ["foo < 1.2"],
        }
    )
    assert result["summary"] == "RCE"
    assert result["attack_complexity"] == "High"
    assert result["recommended_timeline"] == "HIGH (7 days)"
    assert result["affected_version"] == "foo < 1.2"
    assert result["analysis_timestamp"] != "2020-01-01"


def test_cve_validator_prompt_stops_asking_computed_fields() -> None:
    for key in (
        "attack_complexity",
        "recommended_timeline",
        "affected_version",
        "analysis_timestamp",
    ):
        assert key not in cve_email._VALIDATOR_PROMPT


def test_cve_input_is_json_capped() -> None:
    cve_data: dict[str, Any] = {
        "cve_id": "CVE-2026-0001",
        "tech": "foo",
        "summary": "x" * 20_000,
        "cve_severity": "HIGH",
        "cve_score": 8.1,
        "cvss_vector": "CVSS:3.1/AV:N/AC:L",
        "published": "2026-10-01T00:00:00",
        "solutions": "y" * 10_000,
        "affected": [f"product {i} < 1.{i}" for i in range(500)],
        "reference": [f"https://example.com/advisory/{i}" for i in range(500)],
    }
    msg = cve_email._cve_user_message(cve_data)
    assert len(msg) <= 6000
    parsed = json.loads(msg)
    assert parsed["cve_id"] == "CVE-2026-0001"
    assert parsed["cvss_vector"] == "CVSS:3.1/AV:N/AC:L"


def test_cve_input_small_is_unchanged() -> None:
    cve_data = {"cve_id": "CVE-2026-0002", "summary": "short", "affected": ["a"]}
    assert json.loads(cve_email._cve_user_message(cve_data)) == cve_data


def test_mitigation_prompt_not_exactly_7() -> None:
    assert "5 to 7" in cve_email._MITIGATION_PROMPT
    assert "EXACTLY 7" not in cve_email._MITIGATION_PROMPT


# ── 2. TA profile ────────────────────────────────────────────────────────────


def test_ta_prompt_requires_context_only() -> None:
    prompt = ta_profile._SYSTEM_PROMPT
    rule_start = prompt.index("only from the provided context")
    rule = prompt[rule_start - 400 : rule_start + 400]
    for field in (
        "known_malware",
        "exploited_vulnerabilities",
        "attack_techniques",
        "known_iocs",
    ):
        assert field in rule
    assert "empty" in rule


def test_ta_overrides() -> None:
    now = datetime.datetime(2026, 10, 24, 3, 0, tzinfo=datetime.UTC)
    profile: dict[str, Any] = {
        "profile_metadata": {"generated_at": "2019-01-01", "tlp_marking": "TLP:RED"},
        "identity": {"tracking_ids": {"mitre_group_id": "G9999", "other_ids": ["UNC1"]}},
    }
    out = ta_profile.apply_overrides(profile, "G0096", now)
    assert out["profile_metadata"]["generated_at"] == now.isoformat()
    assert out["profile_metadata"]["tlp_marking"] == "TLP:CLEAR"
    assert out["identity"]["tracking_ids"]["mitre_group_id"] == "G0096"
    assert out["identity"]["tracking_ids"]["other_ids"] == ["UNC1"]


def test_ta_overrides_create_missing_dicts_and_null_id() -> None:
    now = datetime.datetime(2026, 10, 24, tzinfo=datetime.UTC)
    out = ta_profile.apply_overrides({"identity": None}, None, now)
    assert out["profile_metadata"] == {"generated_at": now.isoformat(), "tlp_marking": "TLP:CLEAR"}
    assert out["identity"]["tracking_ids"]["mitre_group_id"] is None


def test_ta_techniques_keep_only_ids_from_context() -> None:
    context = "- Techniques:\n  - T1059.001 PowerShell (execution)\n  - T1486 Data Encrypted"
    profile: dict[str, Any] = {
        "capability_assessment": {
            "attack_techniques": {
                "execution": ["T1059.001 PowerShell (execution)", "T1059.004 Unix Shell"],
                "impact": ["T1486 Data Encrypted for Impact", "T1485 Data Destruction"],
                "discovery": ["Network scanning"],
            }
        }
    }
    out = ta_profile.filter_techniques_to_context(profile, context)
    assert out["capability_assessment"]["attack_techniques"] == {
        "execution": ["T1059.001 PowerShell (execution)"],
        "impact": ["T1486 Data Encrypted for Impact"],
        "discovery": [],
    }


def test_ta_techniques_parent_id_does_not_admit_subtechnique() -> None:
    profile: dict[str, Any] = {
        "capability_assessment": {"attack_techniques": {"execution": ["T1059.001 PowerShell"]}}
    }
    out = ta_profile.filter_techniques_to_context(profile, "- T1059 Command and Scripting")
    assert out["capability_assessment"]["attack_techniques"]["execution"] == []


def test_ta_techniques_filter_tolerates_missing_or_odd_shapes() -> None:
    assert ta_profile.filter_techniques_to_context({}, "T1059") == {}
    odd: dict[str, Any] = {"capability_assessment": {"attack_techniques": ["T1059"]}}
    assert ta_profile.filter_techniques_to_context(odd, "T1059") == odd


def test_ta_user_message_without_attack_match() -> None:
    msg = ta_profile._build_user_message("Foo Group", [], None)
    assert "Foo Group" in msg
    assert "No MITRE ATT&CK group matches" in msg
