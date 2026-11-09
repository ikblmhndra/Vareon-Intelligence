"""Parser live lookup CVE (`cve_live_lookup`): payload NVD 2.0 dan CVE JSON 5 (CIRCL) ke field
seragam, plus aturan gabung (NVD, CIRCL, mirror; nilai tak kosong pertama menang)."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from cti_api.services.cve_live_lookup import merge_fields, parse_circl, parse_nvd

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cve_live_lookup"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())  # type: ignore[no-any-return]


def test_parse_nvd_fields() -> None:
    parsed = parse_nvd(load("nvd_cve_2024_3400.json"))
    assert parsed is not None
    assert parsed["summary"].startswith("A command injection vulnerability")
    assert parsed["cvss_score"] == 9.8
    assert parsed["cvss_severity"] == "CRITICAL"
    assert parsed["cvss_vector"].startswith("CVSS:3.1/")
    assert parsed["cwe"] == ["CWE-77"]
    assert parsed["published"] == datetime.date(2024, 4, 12)
    assert parsed["kev"].added == datetime.date(2024, 4, 12)
    assert parsed["kev"].due == datetime.date(2024, 4, 19)
    assert parsed["kev"].action
    assert "https://security.paloaltonetworks.com/CVE-2024-3400" in parsed["references"]
    assert any("pan-os" in line for line in parsed["affected"])


def test_parse_nvd_empty_is_none() -> None:
    assert parse_nvd({"vulnerabilities": []}) is None


def test_parse_circl_fields() -> None:
    parsed = parse_circl(load("circl_cve_2024_3400.json"))
    assert parsed is not None
    assert parsed["summary"].startswith("A command injection as a result")
    assert parsed["affected"] == [
        "Palo Alto Networks PAN-OS 10.2 < 10.2.9-h1",
        "Palo Alto Networks PAN-OS 11.0 < 11.0.4-h1",
    ]
    assert parsed["cwe"] == ["CWE-77"]
    assert parsed["cvss_score"] == 10.0


def test_parse_circl_without_containers_is_none() -> None:
    assert parse_circl({"error": "not found"}) is None


def test_merge_prefers_nvd_then_circl_then_mirror() -> None:
    nvd = {"summary": "", "cvss_score": 9.8, "cwe": []}
    circl = {"summary": "dari CIRCL", "cvss_score": 10.0, "cwe": ["CWE-77"]}
    mirror = {"summary": "dari mirror", "affected": ["PAN-OS"]}
    merged = merge_fields(nvd, circl, None, mirror)
    assert merged["summary"] == "dari CIRCL"
    assert merged["cvss_score"] == 9.8
    assert merged["cwe"] == ["CWE-77"]
    assert merged["affected"] == ["PAN-OS"]
