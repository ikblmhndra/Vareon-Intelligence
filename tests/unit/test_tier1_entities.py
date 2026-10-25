"""Tes entity dictionary + matcher tier 1 (pure, tanpa DB/HTTP)."""

from __future__ import annotations

import time

from cti_enrich.tier1.dictionary import EntityDictionary, build_dictionary
from cti_enrich.tier1.entities import match_entities


def _dictionary(order: int = 1) -> EntityDictionary:
    groups = [
        ("APT29", ["Cozy Bear", "NOBELIUM"]),
        ("Lazarus Group", ["HIDDEN COBRA"]),
        ("Cobalt Group", ["Cobalt"]),
    ]
    software = [
        ("Cobalt Strike", "tool", []),
        ("Emotet", "malware", ["Geodo"]),
        ("Lazarus Group", "malware", []),
    ]
    ta_names = ["castle", "kimsuky", "shinyhunters", "emotet"]
    if order < 0:
        groups.reverse()
        software.reverse()
        ta_names.reverse()
    return build_dictionary(groups, software, ta_names, ["shinyhunters"])


def _pairs(text: str) -> list[tuple[str, str]]:
    return [(h.canonical, h.kind) for h in match_entities(text, _dictionary())]


def test_cobalt_strike_is_tool_not_actor():
    assert _pairs("Operators deployed Cobalt Strike beacons.") == [("Cobalt Strike", "tool")]


def test_alias_maps_to_canonical():
    assert _pairs("Cozy Bear phished diplomats") == [("APT29", "actor")]


def test_all_caps_alias_case_sensitive():
    assert _pairs("NOBELIUM struck") == [("APT29", "actor")]
    assert _pairs("nobelium is an element") == []


def test_common_word_needs_context():
    assert _pairs("the castle gate") == []
    assert _pairs("the Castle ransomware gang") == [("castle", "actor")]


def test_single_token_ta_name_needs_context():
    assert _pairs("Kimsuky sent lures") == []
    assert _pairs("North Korean APT Kimsuky sent lures") == [("kimsuky", "actor")]


def test_suppressed_name_dropped():
    assert _pairs("ShinyHunters ransomware group") == []


def test_attack_wins_over_ta_list():
    assert _pairs("Emotet ransomware loader") == [("Emotet", "malware")]


def test_group_and_software_same_name_is_actor():
    assert _pairs("Lazarus Group hackers") == [("Lazarus Group", "actor")]


def test_word_boundary():
    assert _pairs("APT290 and xAPT29") == []


def test_cjk_text_no_false_hits():
    text = "".join(chr(c) for c in (0xD55C, 0xAD6D, 0xC5B4, 0x20, 0x65E5, 0x672C, 0x8A9E, 0x20))
    assert _pairs(text) == []
    assert _pairs(text + " APT29 " + text) == [("APT29", "actor")]


def test_dictionary_version_stable():
    assert _dictionary(1).version == _dictionary(-1).version


def test_matcher_speed_on_large_text():
    names = [f"synthgroup{i:04d}x" for i in range(5000)]
    dictionary = build_dictionary([(n, []) for n in names], [], [], [])
    text = ("Lorem ipsum dolor sit amet synthgroup0042x consectetur. " * 2000)[:100_000]
    start = time.perf_counter()
    hits = match_entities(text, dictionary)
    assert time.perf_counter() - start < 2.0
    assert [h.canonical for h in hits] == ["synthgroup0042x"]


def test_ta_name_clashing_with_case_sensitive_attack_key_loses():
    dictionary = build_dictionary(
        [("APT29", ["Cozy Bear"])], [("Emotet", "malware", [])], ["apt29"], []
    )
    hits = match_entities("APT29 hackers", dictionary)
    assert [(h.canonical, h.kind) for h in hits] == [("APT29", "actor")]


def test_unicode_case_folding_chars_do_not_crash():
    dictionary = build_dictionary([("Lazarus", [])], [("Kimsuky", "malware", [])], [], [])
    for text in (f"Lazaru{chr(0x17F)} group", f"{chr(0x212A)}imsuky malware"):
        assert match_entities(text, dictionary) == []
    assert [h.canonical for h in match_entities("LAZARUS group", dictionary)] == ["Lazarus"]


def _eval_dictionary() -> EntityDictionary:
    # P4 eval: nama utilitas Windows / kata biasa dari ATT&CK memicu false positive.
    groups = [("Equation", []), ("Silence", []), ("RTM", []), ("Comando", ["comando"])]
    software = [
        ("at", "tool", []),
        ("cmd", "tool", []),
        ("Net", "tool", []),
        ("Reg", "tool", []),
        ("route", "tool", []),
        ("Expand", "tool", []),
        ("netstat", "tool", []),
        ("Tor", "tool", []),
        ("Nltest", "tool", []),
    ]
    return build_dictionary(groups, software, [], [])


def _eval_pairs(text: str) -> list[tuple[str, str]]:
    return [(h.canonical, h.kind) for h in match_entities(text, _eval_dictionary())]


def test_windows_utility_names_never_match_bare_word():
    assert _eval_pairs("Run at 10pm") == []
    assert _eval_pairs("the net result was bad") == []
    assert _eval_pairs("route traffic through a proxy") == []
    assert _eval_pairs("expand access to the network") == []
    assert _eval_pairs("ran reg and cmd by hand") == []


def test_windows_utility_matches_exe_form_with_canonical_name():
    assert _eval_pairs("attackers ran cmd.exe /C whoami") == [("cmd", "tool")]
    assert _eval_pairs("then NET.EXE user /add") == [("Net", "tool")]
    assert _eval_pairs("scheduled via at.exe") == [("at", "tool")]


def test_distinctive_names_stay_normal():
    assert _eval_pairs("they used netstat and Nltest") == [
        ("netstat", "tool"),
        ("Nltest", "tool"),
    ]


def test_common_word_software_and_groups_need_context():
    assert _eval_pairs("the Tor network is popular") == []
    assert _eval_pairs("the ransomware used Tor to exfiltrate") == [("Tor", "tool")]
    assert _eval_pairs("Equation of state") == []
    assert _eval_pairs("the Equation group struck") == [("Equation", "actor")]
    assert _eval_pairs("RTM is a benchmark") == []  # key case-sensitive "RTM"
    assert _eval_pairs("the RTM group used a backdoor") == [("RTM", "actor")]
    assert _eval_pairs("a harvester and comando team") == []
