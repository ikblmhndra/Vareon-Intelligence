from cti_core.attack_ttp import NormalizedTTP
from cti_enrich.stages.extract_ttps import Technique, TtpResult
from cti_enrich.tier1.merge import confidence_ttp_count, merge_industries, merge_ttps
from cti_enrich.tier1.ttps import SourcedTechnique


def _s(tid: str, source: str, ev: str = "e") -> SourcedTechnique:
    return SourcedTechnique(tid, f"name-{tid}", source, ev)  # type: ignore[arg-type]


def test_explicit_beats_llm_beats_keyword() -> None:
    llm = TtpResult(True, [Technique("T1059.001", "PowerShell", "a")])
    tier1 = [_s("T1059.001", "explicit", "b"), _s("T1486", "keyword"), _s("T1059.001", "keyword")]
    out = merge_ttps(llm, tier1)
    assert [(t.ttp_id, t.source, t.evidence) for t in out] == [
        ("T1059.001", "explicit", "b"),
        ("T1486", "keyword", "e"),
    ]


def test_llm_beats_keyword_keeps_extracted() -> None:
    llm = TtpResult(
        True,
        [
            Technique(
                "T1190", "Exploit Public-Facing Application", "x", "T1190", "Exploit public app"
            )
        ],
    )
    out = merge_ttps(llm, [_s("T1190", "keyword")])
    assert len(out) == 1
    assert out[0].source == "llm"
    assert out[0].extracted_name == "Exploit public app"
    assert out[0].evidence == "x"


def test_none_llm() -> None:
    out = merge_ttps(None, [_s("T1486", "keyword"), _s("T1190", "explicit")])
    assert [(t.ttp_id, t.source) for t in out] == [("T1486", "keyword"), ("T1190", "explicit")]


def test_general_replaced_only_when_tier1_found() -> None:
    fin = "Finance & Insurance"
    assert merge_industries(["General"], [fin]) == ([fin], "keyword")
    assert merge_industries(["General"], []) == (["General"], "llm")
    hc = "Healthcare & Life Sciences"
    assert merge_industries([hc], [fin]) == ([hc], "llm")
    assert merge_industries([], ["Energy & Utilities"]) == (["Energy & Utilities"], "keyword")


def test_confidence_counts_only_explicit_and_llm() -> None:
    ttps = [
        NormalizedTTP("T1", "a", source="explicit"),
        NormalizedTTP("T2", "b"),
        NormalizedTTP("T3", "c", source="keyword"),
    ]
    assert confidence_ttp_count(ttps) == 2


def test_normalized_ttp_backward_compatible() -> None:
    t = NormalizedTTP("T1", "x")
    assert t.source == "llm"
    assert t.evidence is None
