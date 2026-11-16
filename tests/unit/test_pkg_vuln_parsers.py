"""Unit test fungsi murni `cti_api.services.pkg_vuln` -- parsing CVSS/
severity, extraction helper, dan 6 parser lockfile. Gak butuh DB/network.
Fase 7.3 (router `pkg_vuln`, Bagian 4)."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services import pkg_vuln as svc

# ── CVSS / severity ──────────────────────────────────────────────────────────


def test_cvss_vector_to_score_critical() -> None:
    # CVE-2021-44228 (Log4Shell) vector -- skor CVSS resmi 10.0
    vector = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"
    score = svc._cvss_vector_to_score(vector)
    assert score == 10.0
    assert svc._score_to_label(score) == "CRITICAL"


def test_cvss_vector_to_score_invalid_returns_none() -> None:
    assert svc._cvss_vector_to_score("") is None
    assert svc._cvss_vector_to_score("not-a-vector") is None


def test_normalize_sev_str_moderate_maps_to_medium() -> None:
    assert svc._normalize_sev_str("Moderate") == "MEDIUM"
    assert svc._normalize_sev_str("critical") == "CRITICAL"
    assert svc._normalize_sev_str("banana") == "UNKNOWN"


def test_parse_severity_prefers_cvss_vector() -> None:
    osv_vuln = {
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
        "database_specific": {"severity": "LOW"},
    }
    label, score = svc._parse_severity(osv_vuln)
    assert label == "CRITICAL"
    assert score is not None and score >= 9.0


def test_parse_severity_falls_back_to_database_specific() -> None:
    osv_vuln = {"database_specific": {"severity": "HIGH"}}
    label, score = svc._parse_severity(osv_vuln)
    assert label == "HIGH"
    assert score == 7.5


def test_parse_severity_unknown_when_nothing_present() -> None:
    assert svc._parse_severity({}) == ("UNKNOWN", None)


def test_compute_adjusted_score_no_cvss_returns_none() -> None:
    assert svc._compute_adjusted_score(None, 0.9, True) == (None, None)


def test_compute_adjusted_score_kev_boosts_score() -> None:
    adj, sev = svc._compute_adjusted_score(6.0, None, True)
    assert adj == 9.0  # 6.0 * 1.5
    assert sev == "CRITICAL"  # >= 9.0 threshold


def test_compute_adjusted_score_high_epss_boosts_score() -> None:
    adj, _ = svc._compute_adjusted_score(6.0, 0.6, False)
    assert adj == 7.8  # 6.0 * 1.3


def test_compute_adjusted_score_caps_at_ten() -> None:
    adj, sev = svc._compute_adjusted_score(9.8, 0.9, True)
    assert adj == 10.0
    assert sev == "CRITICAL"


# ── Extraction helpers ───────────────────────────────────────────────────────


def test_extract_fixed_version_picks_latest() -> None:
    osv_vuln = {
        "affected": [
            {"ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.2.0"}]}]},
            {"ranges": [{"events": [{"fixed": "1.5.0"}]}]},
        ]
    }
    assert svc._extract_fixed_version(osv_vuln) == "1.5.0"


def test_extract_version_ranges() -> None:
    osv_vuln = {
        "affected": [{"ranges": [{"events": [{"introduced": "1.0.0"}, {"fixed": "2.0.0"}]}]}]
    }
    assert svc._extract_version_ranges(osv_vuln) == [">= 1.0.0, < 2.0.0"]


def test_extract_references_capped_at_ten() -> None:
    osv_vuln = {"references": [{"url": f"https://example.com/{i}"} for i in range(15)]}
    assert len(svc._extract_references(osv_vuln)) == 10


def test_extract_date_parses_iso_prefix() -> None:
    assert svc._extract_date("2024-03-15T12:00:00Z") == datetime.date(2024, 3, 15)


def test_extract_date_none_and_malformed() -> None:
    assert svc._extract_date(None) is None
    assert svc._extract_date("not-a-date") is None


# ── Lockfile parsers ─────────────────────────────────────────────────────────


def test_parse_requirements_txt() -> None:
    content = "# comment\nrequests==2.31.0\nflask\n-e git+https://example.com/x\n"
    result = svc.parse_requirements_txt(content)
    assert ("requests", "PyPI", "2.31.0") in result
    assert ("flask", "PyPI", None) in result
    assert len(result) == 2


def test_parse_package_json() -> None:
    content = '{"dependencies": {"lodash": "^4.17.21"}, "devDependencies": {"jest": "*"}}'
    result = svc.parse_package_json(content)
    assert ("lodash", "npm", "4.17.21") in result
    assert ("jest", "npm", None) in result


def test_parse_package_lock_json_v2() -> None:
    content = '{"packages": {"": {}, "node_modules/lodash": {"version": "4.17.21"}}}'
    result = svc.parse_package_lock_json(content)
    assert ("lodash", "npm", "4.17.21") in result


def test_parse_go_mod() -> None:
    content = "module example.com/x\n\nrequire (\n\tgithub.com/pkg/errors v0.9.1\n)\n"
    result = svc.parse_go_mod(content)
    assert ("github.com/pkg/errors", "Go", "0.9.1") in result


def test_parse_pom_xml() -> None:
    content = """<project>
      <dependencies>
        <dependency>
          <groupId>org.apache.commons</groupId>
          <artifactId>commons-lang3</artifactId>
          <version>3.12.0</version>
        </dependency>
      </dependencies>
    </project>"""
    result = svc.parse_pom_xml(content)
    assert ("org.apache.commons:commons-lang3", "Maven", "3.12.0") in result


def test_parse_poetry_lock() -> None:
    content = (
        '[[package]]\nname = "requests"\nversion = "2.31.0"\n\n'
        '[[package]]\nname = "flask"\nversion = "3.0.0"\n'
    )
    result = svc.parse_poetry_lock(content)
    assert ("requests", "PyPI", "2.31.0") in result
    assert ("flask", "PyPI", "3.0.0") in result


def test_detect_and_parse_lockfile_by_filename() -> None:
    assert svc.detect_and_parse_lockfile("requirements.txt", "flask==3.0.0") == [
        ("flask", "PyPI", "3.0.0")
    ]
    assert svc.detect_and_parse_lockfile(
        "package.json", '{"dependencies": {"lodash": "4.17.21"}}'
    ) == [("lodash", "npm", "4.17.21")]


def test_parse_gemfile_lock() -> None:
    content = (
        "GEM\n  remote: https://rubygems.org/\n  specs:\n"
        "    rails (7.1.3)\n      actionpack (= 7.1.3)\n"
        "    rack (3.0.9)\n\nPLATFORMS\n  ruby\n\nDEPENDENCIES\n  rails\n"
    )
    result = svc.parse_gemfile_lock(content)
    assert ("rails", "RubyGems", "7.1.3") in result
    assert ("rack", "RubyGems", "3.0.9") in result
    assert all(name != "actionpack" for name, _, _ in result)  # dependensi turunan bukan spec


def test_parse_yarn_lock_v1() -> None:
    content = (
        "# yarn lockfile v1\n\n"
        'lodash@^4.17.0, lodash@^4.17.21:\n  version "4.17.21"\n  resolved "x"\n\n'
        '"@babel/core@^7.0.0":\n  version "7.23.0"\n'
    )
    result = svc.parse_yarn_lock(content)
    assert ("lodash", "npm", "4.17.21") in result
    assert ("@babel/core", "npm", "7.23.0") in result


def test_parse_yarn_lock_berry() -> None:
    content = (
        '__metadata:\n  version: 6\n\n"lodash@npm:^4.17.21":\n  version: 4.17.21\n'
        '  resolution: "lodash@npm:4.17.21"\n\n"@babel/core@npm:^7.0.0":\n  version: 7.23.0\n'
    )
    result = svc.parse_yarn_lock(content)
    assert ("lodash", "npm", "4.17.21") in result
    assert ("@babel/core", "npm", "7.23.0") in result
    assert all(name != "__metadata" for name, _, _ in result)


def test_parse_go_sum_dedupes_and_drops_go_mod() -> None:
    content = (
        "github.com/pkg/errors v0.9.1 h1:abc=\n"
        "github.com/pkg/errors v0.9.1/go.mod h1:def=\n"
        "bad line\n"
    )
    assert svc.parse_go_sum(content) == [("github.com/pkg/errors", "Go", "0.9.1")]


def test_unknown_lockfile_auto_raises() -> None:
    with pytest.raises(svc.UnknownLockfileError):
        svc.parse_lockfile("deps.txt", "flask==3.0.0", "auto")


def test_explicit_ecosystem_picks_parser_for_unknown_name() -> None:
    fmt, pkgs = svc.parse_lockfile("deps.txt", "flask==3.0.0", "PyPI")
    assert fmt == "requirements"
    assert pkgs == [("flask", "PyPI", "3.0.0")]


def test_recognised_name_ignores_override() -> None:
    fmt, _ = svc.parse_lockfile("package-lock.json", "{}", "PyPI")
    assert fmt == "package-lock"


def test_detect_lockfile_format() -> None:
    assert svc.detect_lockfile_format("Gemfile.lock") == "gemfile-lock"
    assert svc.detect_lockfile_format("yarn.lock") == "yarn-lock"
    assert svc.detect_lockfile_format("go.sum") == "go-sum"
    assert svc.detect_lockfile_format("deps.txt") is None
