"""Tes inti skor harness evaluasi Tier 1 (tools/eval/tier1_eval.py)."""

from __future__ import annotations

from cti_core.attack_ttp import TechniqueCatalog
from cti_enrich.tier1.dictionary import build_dictionary

from tools.eval.tier1_eval import (
    Label,
    agreement_rate,
    build_candidates,
    score_precision,
)


def test_score_precision_counts_per_source() -> None:
    labels = [
        Label("1:ttp:T1566", True, "q", "subagent"),
        Label("2:ttp:T1059", False, "q", "subagent"),
        Label("3:actor:apt29", True, "q", "subagent"),
    ]
    prov = {
        "1:ttp:T1566": {"explicit", "llm"},
        "2:ttp:T1059": {"keyword"},
        "3:actor:apt29": {"dictionary"},
    }
    got = score_precision(labels, prov)
    assert got[("ttp", "explicit")] == (1, 1)
    assert got[("ttp", "llm")] == (1, 1)
    assert got[("ttp", "keyword")] == (0, 1)
    assert got[("actor", "dictionary")] == (1, 1)


def test_agreement_rate() -> None:
    labels = [
        Label("a:ttp:T1", True, "", "subagent"),
        Label("a:ttp:T1", True, "", "user"),
        Label("b:ttp:T2", True, "", "subagent"),
        Label("b:ttp:T2", False, "", "user"),
        Label("c:ttp:T3", True, "", "subagent"),  # hanya satu pelabel: tidak dihitung
    ]
    assert agreement_rate(labels) == (1, 2)


def test_candidates_have_no_source_field() -> None:
    dictionary = build_dictionary([("APT29", ["Cozy Bear"])], [], [], [])
    catalog = TechniqueCatalog(names={"T1566": "Phishing"})
    article = {"id": 7, "title": "APT29 uses T1566", "actors": ["Apt29"], "ttps": []}
    candidates, _ = build_candidates(
        article, "APT29 used T1566 against embassies.", dictionary, catalog
    )
    assert candidates
    for c in candidates:
        assert set(c.row()) == {"candidate_id", "article_id", "field", "value"}
    actor = next(c for c in candidates if c.field == "actor")
    assert actor.sources == {"dictionary", "llm"}


def test_json_lines_skips_psql_command_tags() -> None:
    from tools.eval.tier1_eval import _json_lines

    assert _json_lines('SET\n{"id": 1}\n\n{"id": 2}\n') == ['{"id": 1}', '{"id": 2}']


def test_written_order_does_not_depend_on_source() -> None:
    from tools.eval.tier1_eval import Candidate, shuffle_key

    a = [Candidate(i, "ttp", f"T{i}", frozenset({s})) for i, s in enumerate(["llm", "keyword"] * 5)]
    b = [Candidate(c.article_id, c.field, c.value, frozenset({"dictionary"})) for c in a]
    order_a = [c.candidate_id for c in sorted(a, key=lambda c: shuffle_key(c.candidate_id))]
    order_b = [c.candidate_id for c in sorted(b, key=lambda c: shuffle_key(c.candidate_id))]
    assert order_a == order_b


def test_general_industry_is_not_a_candidate() -> None:
    dictionary = build_dictionary([], [], [], [])
    article = {"id": 1, "title": "x", "industries": ["General"]}
    candidates, merged = build_candidates(article, "", dictionary, TechniqueCatalog(names={}))
    assert not [c for c in candidates if c.field == "industry"]
    assert "general" not in merged["industry"]
