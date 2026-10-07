"""`cti_core.tech_match` -- satu definisi "teks ini menyebut tech itu" (ROADMAP #19 fase 1).

Kasus-kasusnya diambil dari kejadian nyata di `docs/CVE_TECH_MATCHING.md` (laporan
`reconcile_cve_tech` produksi 2026-10-07), bukan karangan."""

from __future__ import annotations

import pytest
from cti_core.tech_match import (
    aliases_of,
    matching_names,
    mentions,
    mentions_any,
    normalize,
    terms,
)


@pytest.mark.parametrize(
    ("tech", "text", "aliases", "expected"),
    [
        # --- cocok -------------------------------------------------------------------------
        ("graylog", "graylog2-server", (), True),  # angka menempel = versi mayor (f96d23b)
        ("log4j", "Apache Log4j2", (), True),
        ("struts", "Struts2", (), True),
        ("palo alto", "Palo_Alto-Networks", (), True),
        ("palo alto", "Palo Alto Networks PAN-OS", (), True),
        ("microsoft 365", "Microsoft 365 Apps", (), True),
        ("nginx", "F5 NGINX Plus", (), True),
        ("nginx", "nginx-ui", (), True),  # batas kata -> masih cocok (batasan leksikal, doc 6)
        ("node.js", "Node.js 20 LTS", (), True),  # titik di nama tech tidak jadi regex
        # --- alias: nama lain yang ditulis CNA ----------------------------------------------
        ("palo alto", "PAN-OS", ("pan-os",), True),
        ("palo alto", "paloaltonetworks", ("paloaltonetworks",), True),
        ("mikrotik", "RouterOS", ("routeros",), True),
        ("perimeter81", "Perimeter 81 agent", ("perimeter 81",), True),
        # --- tidak cocok --------------------------------------------------------------------
        ("palo alto", "PAN-OS", (), False),  # tanpa alias, nama lain memang tidak cocok
        ("jira", "mcp-atlassian", (), False),  # 29 dari 52 baris salah di produksi
        ("jira", "GoCD project-management", (), False),
        ("go", "google chrome", (), False),  # substring tanpa batas kata (#5 lama)
        ("go", "Django", (), False),
        ("nginx", "nginxy", (), False),  # huruf menempel = produk lain
        ("nginx", "nginxplus", (), False),
        ("edge", "knowledge base", (), False),
        ("grafana", "Pandora FMS", (), False),
        ("mariadb", "Zabbix", (), False),
        ("microsoft 365", "Microsoft 36", (), False),
        ("graylog", "grey log", (), False),
        # --- istilah terlalu pendek tidak pernah cocok --------------------------------------
        ("c++", "vitamin c is good", (), False),
        ("", "apa saja", (), False),
        ("nginx", "", (), False),
    ],
)
def test_mentions(tech: str, text: str, aliases: tuple[str, ...], expected: bool) -> None:
    assert mentions(tech, text, aliases) is expected


def test_term_with_regex_metacharacters_does_not_crash_or_overmatch() -> None:
    """`\\b{tech}\\b` tanpa `re.escape` (score.py #4 lama) meledak/salah pada `c++`, `.net`."""
    for weird in ("c++", ".net", "node.js", "(x", "a|b", "[abc]"):
        mentions(weird, "plain text with no such thing")  # tidak boleh raise


def test_normalize_and_terms() -> None:
    assert normalize("  Palo_Alto--Networks  ") == "palo alto networks"
    assert terms("Palo Alto", ["PAN-OS", "pan os", "x"]) == (
        "palo alto",
        "pan os",
    )  # dedup, "x" dibuang
    assert terms("c++") == ()


def test_aliases_of_uses_normalized_key() -> None:
    alias_map = {"palo alto": ["pan-os"]}
    assert aliases_of("Palo_Alto", alias_map) == ["pan-os"]
    assert aliases_of("fortinet", alias_map) == ()
    assert aliases_of("fortinet", None) == ()


def test_matching_names_keeps_order_and_applies_aliases() -> None:
    names = ["wazuh", "palo alto", "jira", "mikrotik"]
    alias_map = {"palo alto": ["pan-os"], "mikrotik": ["routeros"]}
    text = "Critical PAN-OS bug and RouterOS flaw; mcp-atlassian unaffected"
    assert matching_names(names, text, alias_map) == ["palo alto", "mikrotik"]
    assert matching_names(names, text) == []  # tanpa alias tak ada yang cocok
    assert matching_names(names, "") == []


def test_mentions_any() -> None:
    assert mentions_any(["wazuh", "jira"], "Wazuh 4.9 released") is True
    assert mentions_any(["wazuh", "jira"], "nothing relevant") is False
    assert mentions_any([], "Wazuh") is False
    assert mentions_any(["palo alto"], "PAN-OS", {"palo alto": ["pan-os"]}) is True
