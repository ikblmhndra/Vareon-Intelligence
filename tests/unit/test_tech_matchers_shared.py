"""Semua pencocok tech memakai SATU definisi (`cti_core.tech_match`) -- ROADMAP #19 fase 1.

`test_tech_match.py` mengunci aturannya; di sini dikunci bahwa tiap pemanggil benar-benar
memakainya: `score.py` (judul artikel dan vendor CVE), `cve_priority.in_tech_stack`, penilai
`reconcile_cve_tech`, dan seed alias di migrasi. Kasus diambil dari
`docs/CVE_TECH_MATCHING.md` 2.4 (substring tanpa batas kata, regex tanpa `re.escape`)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from cti_api.services.cve_priority import _in_tech_stack
from cti_core.tech_match import mentions, terms
from cti_enrich.stages.score import check_tech_stack, score_with_lists

from tools.ops.reconcile_cve_tech import Row, plan

ALIASES = {"palo alto": ["paloaltonetworks", "pan-os"], "mikrotik": ["routeros"]}


def _title_hits_tech(title: str, techstack: list[str], aliases=None) -> bool:
    # body "" -> tanpa NER (spaCy tak perlu); judul tanpa CVE -> tanpa HTTP MITRE
    return score_with_lists(
        title,
        "",
        techstack=techstack,
        group_list=[],
        apac_people_list=[],
        tech_aliases=aliases,
    ).related_tech_status


# --- score.py: related_tech_status (#4) ------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "techstack", "aliases", "expected"),
    [
        ("Critical flaw in Wazuh manager", ["wazuh"], None, True),
        ("Palo Alto Networks patches GlobalProtect", ["palo alto"], None, True),
        ("PAN-OS zero-day exploited", ["palo alto"], None, False),  # tanpa alias
        ("PAN-OS zero-day exploited", ["palo alto"], ALIASES, True),
        ("Attackers abuse RouterOS", ["mikrotik"], ALIASES, True),
        ("New Google Chrome release", ["go"], None, False),  # `go` bukan `google`
        ("Why every team should go passwordless", ["jira"], None, False),
        # tech dengan metakarakter regex tidak boleh meledak maupun cocok ke mana-mana
        ("Compiler news for C++ and node.js", ["c++", "node.js"], None, True),  # node.js cocok
        ("Compiler news for vitamin C", ["c++"], None, False),
    ],
)
def test_related_tech_status_uses_the_shared_matcher(
    title: str, techstack: list[str], aliases: dict[str, list[str]] | None, expected: bool
) -> None:
    assert _title_hits_tech(title, techstack, aliases) is expected


# --- score.py: check_tech_stack / vendor CVE (#5) ---------------------------------------------


@pytest.mark.parametrize(
    ("vendor", "techstack", "aliases", "expected"),
    [
        ("Palo Alto Networks", ["palo alto"], None, True),
        ("paloaltonetworks", ["palo alto"], None, False),
        ("paloaltonetworks", ["palo alto"], ALIASES, True),
        ("Google", ["go"], None, False),  # substring lama: "go" in "google" -> True
        ("Atlassian", ["jira"], None, False),
        ("Wazuh, Inc.", ["wazuh"], None, True),
        ("Unknown", ["wazuh"], None, False),
    ],
)
def test_check_tech_stack_vendor_uses_the_shared_matcher(
    vendor: str, techstack: list[str], aliases: dict[str, list[str]] | None, expected: bool
) -> None:
    assert check_tech_stack(vendor, techstack, aliases) is expected


# --- cve_priority.in_tech_stack (#6) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("tracker_tech", "stack", "expected"),
    [
        ("WordPress", [("wordpress", [])], True),
        ("palo alto", [("Palo Alto", [])], True),
        ("PAN-OS", [("palo alto", ["pan-os"])], True),  # lewat alias entri
        ("jira", [("jira service management", [])], True),  # nama tracker di dalam nama entri
        ("go", [("google", [])], False),  # substring dua arah lama: True
        ("google", [("go", [])], False),
        ("edge", [("knowledge base", [])], False),
        ("SomeOtherTech", [("wordpress", [])], False),
        ("", [("wordpress", [])], False),
        ("wordpress", [], False),
    ],
)
def test_in_tech_stack_uses_the_shared_matcher(
    tracker_tech: str, stack: list[tuple[str, list[str]]], expected: bool
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


def test_reconcile_judges_with_the_same_aliases_as_the_scraper() -> None:
    """Kalau penilai tak membawa alias, CVE PAN-OS yang sah dinilai `delete` -- tool membuang
    data yang scraper sendiri akan simpan (satu definisi "cocok", CVE_TECH_MATCHING.md 5)."""
    products = {"CVE-1": ["paloaltonetworks", "PAN-OS"]}
    rows = [_row("palo alto")]

    assert [f.action for f in plan(rows, products, {"acme": ["palo alto"]}).findings] == ["delete"]
    kept = plan(rows, products, {"acme": ["palo alto"]}, ALIASES)
    assert kept.findings == [] and kept.ok == 1


def test_reconcile_retags_to_a_tech_that_matches_only_through_its_alias() -> None:
    products = {"CVE-1": ["MikroTik", "RouterOS"]}
    result = plan([_row("wazuh")], products, {"acme": ["wazuh", "mikrotik"]}, ALIASES)

    assert [(f.action, f.new_tech) for f in result.findings] == [("retag", "mikrotik")]


# --- seed alias di migrasi ---------------------------------------------------------------------

_MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic/versions/a9d4e6f81b3c_techstack_aliases.py"
)


def _seed() -> dict[str, list[str]]:
    spec = importlib.util.spec_from_file_location("migration_techstack_aliases", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._SEED_ALIASES  # type: ignore[no-any-return]


def test_seed_aliases_are_lowercase_keys_and_every_alias_is_matchable() -> None:
    for name, aliases in _seed().items():
        assert name == name.lower(), f"kunci seed harus lower(name): {name!r}"
        assert aliases, f"{name!r} tanpa alias tidak perlu ada di seed"
        for alias in aliases:
            # alias yang dinormalisasi jadi terlalu pendek tidak pernah cocok = seed sia-sia
            assert len(terms(alias)) == 1, f"alias {alias!r} untuk {name!r} tidak bisa dicocokkan"


def test_seed_aliases_fix_the_real_cases_and_stay_conservative() -> None:
    seed = _seed()
    assert mentions("palo alto", "PAN-OS", seed["palo alto"])
    assert mentions("palo alto", "paloaltonetworks", seed["palo alto"])
    assert mentions("mikrotik", "RouterOS", seed["mikrotik"])
    assert mentions("perimeter81", "Perimeter 81", seed["perimeter81"])
    # alias tidak boleh membawa balik kelas masalah: produk lain yang kebetulan menyebutnya
    for name, aliases in seed.items():
        for text in ("mcp-atlassian", "Zabbix", "knowledge base", "google chrome"):
            assert not mentions(name, text, aliases), f"{name!r} + alias cocok ke {text!r}"
