"""Pencocok tech memakai SATU definisi (`cti_core.tech_match`) -- ROADMAP #19.

`test_tech_match.py` mengunci aturannya; di sini dikunci bahwa tiap pemanggil benar-benar
memakainya: `score.py` (judul artikel dan vendor CVE), `cve_priority.in_tech_stack`, dan
penilai `reconcile_cve_tech`. Kasus diambil dari `docs/CVE_TECH_MATCHING.md` 2.4 (substring tanpa
batas kata, regex tanpa `re.escape`)."""

from __future__ import annotations

import pytest
from cti_api.services.cve_priority import _in_tech_stack
from cti_enrich.stages.score import check_tech_stack, score_with_lists

from tools.ops.reconcile_cve_tech import Row, plan


def _title_hits_tech(title: str, techstack: list[str]) -> bool:
    # body "" -> tanpa NER (spaCy tak perlu); judul tanpa CVE -> tanpa HTTP MITRE
    return score_with_lists(
        title, "", techstack=techstack, group_list=[], apac_people_list=[]
    ).related_tech_status


# --- score.py: related_tech_status (#4) ------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "techstack", "expected"),
    [
        ("Critical flaw in Wazuh manager", ["wazuh"], True),
        ("Palo Alto Networks patches GlobalProtect", ["palo alto"], True),
        ("New Google Chrome release", ["go"], False),  # `go` bukan `google`
        ("Why every team should go passwordless", ["jira"], False),
        # tech dengan metakarakter regex tidak boleh meledak maupun cocok ke mana-mana
        ("Compiler news for C++ and node.js", ["c++", "node.js"], True),  # node.js cocok
        ("Compiler news for vitamin C", ["c++"], False),
    ],
)
def test_related_tech_status_uses_the_shared_matcher(
    title: str, techstack: list[str], expected: bool
) -> None:
    assert _title_hits_tech(title, techstack) is expected


# --- score.py: check_tech_stack / vendor CVE (#5) ---------------------------------------------


@pytest.mark.parametrize(
    ("vendor", "techstack", "expected"),
    [
        ("Palo Alto Networks", ["palo alto"], True),
        ("Google", ["go"], False),  # substring lama: "go" in "google" -> True
        ("Atlassian", ["jira"], False),
        ("Wazuh, Inc.", ["wazuh"], True),
        ("Unknown", ["wazuh"], False),
    ],
)
def test_check_tech_stack_vendor_uses_the_shared_matcher(
    vendor: str, techstack: list[str], expected: bool
) -> None:
    assert check_tech_stack(vendor, techstack) is expected


# --- cve_priority.in_tech_stack (#6) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("tracker_tech", "stack", "expected"),
    [
        ("WordPress", ["wordpress"], True),
        ("palo alto", ["Palo Alto"], True),
        ("jira", ["jira service management"], True),  # nama tracker di dalam nama entri
        ("go", ["google"], False),  # substring dua arah lama: True
        ("google", ["go"], False),
        ("edge", ["knowledge base"], False),
        ("SomeOtherTech", ["wordpress"], False),
        ("", ["wordpress"], False),
        ("wordpress", [], False),
    ],
)
def test_in_tech_stack_uses_the_shared_matcher(
    tracker_tech: str, stack: list[str], expected: bool
) -> None:
    assert _in_tech_stack(tracker_tech, stack) is expected


# --- reconcile_cve_tech.plan -------------------------------------------------------------------


def _row(tech: str) -> Row:
    return Row(
        id=1,
        cve_id="CVE-1",
        client_id="acme",
        tech=tech,
        summary="",
        affected=("PAN-OS: < 11",),
        has_ticket=False,
    )


def test_reconcile_uses_the_same_whole_word_rule_as_the_scraper() -> None:
    products = {"CVE-1": ["Palo Alto Networks", "PAN-OS"]}
    kept = plan([_row("palo alto")], products, {"acme": ["palo alto"]})
    assert kept.findings == [] and kept.ok == 1

    # produk lain yang kebetulan menyebut tech di deskripsi tetap `delete`
    other = plan([_row("jira")], {"CVE-1": ["mcp-atlassian"]}, {"acme": ["jira"]})
    assert [f.action for f in other.findings] == ["delete"]
