"""Tes tier 1: teknik ATT&CK eksplisit (ID di teks) dan keyword."""

from __future__ import annotations

import re

from cti_core.attack_ttp import TechniqueCatalog
from cti_enrich.tier1.keyword_map import KEYWORD_MAP, KEYWORD_MAP_VERSION, sentence_at
from cti_enrich.tier1.ttps import extract_techniques

CATALOG = TechniqueCatalog(
    names={
        "T1059": "Command and Scripting Interpreter",
        "T1059.001": "PowerShell",
        "T1486": "Data Encrypted for Impact",
        "T1566.001": "Spearphishing Attachment",
        "T1505.003": "Web Shell",
        "T1190": "Exploit Public-Facing Application",
    }
)


def test_explicit_ids_validated() -> None:
    text = "Uses T1059.001 and T1059. Not T1000 routers, not T1059.999, not t1059"
    out = extract_techniques(text, CATALOG)
    assert [t.ttp_id for t in out] == ["T1059.001", "T1059"]
    assert all(t.source == "explicit" for t in out)


def test_explicit_beats_keyword() -> None:
    out = extract_techniques("PowerShell (T1059.001) was used", CATALOG)
    assert [(t.ttp_id, t.source) for t in out] == [("T1059.001", "explicit")]


def test_keyword_requires_second_phrase() -> None:
    assert not [t for t in extract_techniques("files were encrypted", CATALOG)]
    out = extract_techniques("the ransomware encrypted files", CATALOG)
    assert [(t.ttp_id, t.source) for t in out] == [("T1486", "keyword")]


def test_keyword_evidence_is_sentence() -> None:
    text = "First sentence here. The actor dropped a web shell on the server. Last one."
    out = extract_techniques(text, CATALOG)
    assert out[0].ttp_id == "T1505.003"
    assert out[0].evidence == "The actor dropped a web shell on the server."


def test_empty_catalog_keeps_keywords_drops_explicit() -> None:
    out = extract_techniques("T1059 via PowerShell", TechniqueCatalog(names={}))
    assert [(t.ttp_id, t.ttp_name, t.source) for t in out] == [
        ("T1059.001", "PowerShell", "keyword")
    ]


def test_keyword_map_size_and_ids() -> None:
    ids = {r.ttp_id for r in KEYWORD_MAP}
    assert len(ids) >= 40
    assert all(re.match(r"^T\d{4}(\.\d{3})?$", i) for i in ids)
    assert len(KEYWORD_MAP_VERSION) == 8


def test_no_bare_tactic_phrases() -> None:
    bare = {
        "execution",
        "persistence",
        "exfiltration",
        "initial access",
        "discovery",
        "collection",
        "impact",
    }
    for rule in KEYWORD_MAP:
        assert not bare & {p.lower() for p in rule.phrases}


def test_pinned_examples() -> None:
    cases = {
        "A spear-phishing attachment was sent": "T1566.001",
        "a malicious link in the mail": "T1566.002",
        "installed a webshell": "T1505.003",
        "They exploited the vulnerability in the VPN": "T1190",
        "exploiting a flaw in an internet-facing server": "T1190",
        "a supply-chain compromise hit vendors": "T1195",
        "dumped credentials from lsass": "T1003",
        "hidden cryptojacking payload": "T1496",
    }
    for text, tid in cases.items():
        assert tid in {t.ttp_id for t in extract_techniques(text, TechniqueCatalog(names={}))}, text


def test_sentence_at_caps_and_collapses() -> None:
    assert sentence_at("x.  Hello\n  world. y", 6) == "Hello world."
    text = "a " * 300 + "TRIGGER PHRASE " + "b " * 300 + "."
    out = sentence_at(text, text.index("TRIGGER"))
    assert len(out) <= 300
    assert "TRIGGER PHRASE" in out


def test_noisy_probe_sentences_yield_nothing() -> None:
    probes = [
        "CVE-2026-1 allows unauthenticated remote code execution in Foo.",
        "Users should avoid clicking malicious links and attachments.",
        "Millions of stolen credentials were posted on a forum.",
        "A local privilege escalation vulnerability was patched.",
        "Valid accounts should be reviewed. Exposed VPN gateways exist.",
        "Malware-as-a-service is a growing market. Malicious scripts are common.",
        "The group did not exploit anything. Internet-facing hosts are common.",
    ]
    for text in probes:
        assert extract_techniques(text, CATALOG) == [], text


def test_actor_context_enables_contextual_rules() -> None:
    out = extract_techniques(
        "Threat actors used stolen credentials to log in.", TechniqueCatalog(names={})
    )
    assert "T1078" in {t.ttp_id for t in out}


def test_keyword_dropped_when_id_not_in_nonempty_catalog() -> None:
    cat = TechniqueCatalog(names={"T1486": "Data Encrypted for Impact"})
    assert extract_techniques("They installed a web shell.", cat) == []


def test_new_rules_t1684_t1685() -> None:
    out = extract_techniques(
        "Attackers impersonated the IT help desk. They disabled EDR on hosts.",
        TechniqueCatalog(names={}),
    )
    assert {"T1684.001", "T1685"} <= {t.ttp_id for t in out}
    out = extract_techniques("Attackers ran a social engineering campaign to steal data.", CATALOG)
    assert out == []  # T1684 tidak ada di katalog uji
    out = extract_techniques(
        "Attackers ran a social engineering campaign to steal data.", TechniqueCatalog(names={})
    )
    assert "T1684" in {t.ttp_id for t in out}
