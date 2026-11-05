import io
import zipfile
from datetime import UTC, datetime

from cti_api.services.hunt_builder import (
    AnchorIn,
    IndicatorIn,
    SigmaIn,
    TechniqueIn,
    build_pack,
    build_spl,
    group_iocs,
    merge_tiers,
    pack_zip,
    select_sigma,
    spl_quote,
)


def _sig(id, techniques, level="high", status="test", ruleset="core"):
    return SigmaIn(
        id=id,
        title=f"rule {id}",
        level=level,
        status=status,
        author="Someone",
        ruleset=ruleset,
        path=f"rules/{id}.yml",
        release="r1",
        techniques=tuple(techniques),
        logsource={"category": "process_creation"},
    )


def _args():
    return dict(
        anchor=AnchorIn("story", 7, "Story", None),
        techniques=[TechniqueIn("T1059", "Cmd", "primary")],
        indicators=[
            IndicatorIn("ip", "198.51.100.7", None, "clear"),
            IndicatorIn("ip", "198.51.100.1", None, "clear"),
            IndicatorIn("url", "http://x/*", None, "clear"),
            IndicatorIn("mutex", "m", None, "clear"),
        ],
        sigma_rules=[_sig("a", ["T1059.001"])],
        include=set(),
        sigma_release="r1",
        truncated=False,
        now=datetime(2026, 11, 4, tzinfo=UTC),
    )


def _pack():
    return build_pack(**_args())


def test_spl_chunks_at_200():
    ips = [IndicatorIn("ip", f"10.0.{i // 256}.{i % 256}", None, "clear") for i in range(450)]
    searches, skipped = build_spl(ips)
    assert [s.value_count for s in searches] == [200, 200, 50] and skipped == 0
    assert searches[0].query.startswith("| tstats summariesonly=false count")
    assert "from datamodel=Network_Traffic.All_Traffic" in searches[0].query
    assert "All_Traffic.src IN (" in searches[0].query
    assert "All_Traffic.dest IN (" in searches[0].query


def test_spl_quotes_ipv6_and_spaces():
    assert spl_quote('a"b\\c') == '"a\\"b\\\\c"'
    assert spl_quote("2001:db8::1") == '"2001:db8::1"'
    assert spl_quote("http://x/a b") == '"http://x/a b"'
    assert spl_quote("http://x/*") is None and spl_quote("a\nb") is None


def test_skipped_values_counted():
    _, skipped = build_spl([IndicatorIn("url", "http://x/*", None, "clear")])
    assert skipped == 1


def test_domain_goes_to_dns_and_web():
    s, _ = build_spl([IndicatorIn("domain", "evil.example", None, "clear")])
    assert {x.dataset for x in s} == {"dns", "web_domain"}


def test_hashes_go_to_both_endpoint_datasets():
    s, _ = build_spl([IndicatorIn("sha256", "a" * 64, None, "clear")])
    assert {x.dataset for x in s} == {"endpoint_processes", "endpoint_filesystem"}


def test_unmapped_type_goes_to_other():
    ind = IndicatorIn("mutex", "x", None, "clear")
    assert group_iocs([ind]) == {"other": [ind]}
    assert build_spl([ind]) == ([], 0)


def test_merge_tiers_keeps_strongest():
    out = merge_tiers([TechniqueIn("T1059", "x", "llm"), TechniqueIn("T1059", "x", "primary")])
    assert out == [TechniqueIn("T1059", "x", "primary")]


def test_select_sigma_match_kinds_and_order():
    t = [
        TechniqueIn("T1059", "", "primary"),
        TechniqueIn("T1566.001", "", "primary"),
        TechniqueIn("T1190", "", "llm"),
    ]
    rules = [
        _sig("a", ["T1059.001"], level="medium"),
        _sig("b", ["T1566"], level="high"),
        _sig("c", ["T1059"], level="critical", ruleset="emerging-threats"),
        _sig("d", ["T1190"], level="critical"),
    ]
    got = select_sigma(t, rules, include=set())
    assert [(m.id, m.match) for m in got] == [("b", "parent"), ("a", "sub"), ("c", "exact")]
    assert "d" in [m.id for m in select_sigma(t, rules, include={"llm"})]
    assert got[0].link == "https://github.com/SigmaHQ/sigma/blob/r1/rules/b.yml"


def _cap_rules():
    t = [TechniqueIn("T1059", "", "primary")]
    rules = [_sig(f"p{i}", ["T1059"], level="low") for i in range(3)]
    rules += [_sig(f"s{i}", ["T1059.001"], level="critical") for i in range(4)]
    rules += [_sig("x", ["T1190"])]
    return t, rules


def test_select_sigma_caps_per_technique_exact_first():
    t, rules = _cap_rules()
    got = select_sigma(t, rules, include=set(), per_technique=5)
    assert len(got) == 5
    assert [m.match for m in got].count("exact") == 3  # exact menang atas sub walau level rendah
    assert select_sigma(t, rules, include=set(), per_technique=0) == select_sigma(
        t, rules, include=set(), per_technique=100
    )
    assert len(select_sigma(t, rules, include=set(), per_technique=0)) == 7
    assert len(select_sigma(t, rules, include=set())) == 5  # default 5


def test_build_pack_sigma_total_and_uncapped_technique_count():
    t, rules = _cap_rules()
    a = _args() | {"techniques": t, "sigma_rules": rules}
    p = build_pack(**a)
    assert len(p.sigma) == 5
    assert p.counts["sigma_total"] == 7
    assert p.techniques[0].sigma_count == 7
    assert len(build_pack(**a, per_technique=0).sigma) == 7


def test_pack_zip_members_and_attribution():
    z = zipfile.ZipFile(io.BytesIO(pack_zip(_pack(), {"a": "title: a"}, "DRL TEXT")))
    names = set(z.namelist())
    assert {"README.md", "LICENSE.Detection.Rules.md", "sigma/a.yml"} <= names
    assert any(n.startswith("spl/") for n in names) and any(n.startswith("iocs/") for n in names)
    readme = z.read("README.md").decode()
    assert "Detection Rule License 1.1" in readme and "author" in readme.lower()
    assert z.read("iocs/network_traffic.csv").decode().startswith("type,value,valid_until,tlp")


def test_build_pack_is_deterministic():
    assert build_pack(**_args()) == build_pack(**_args())


def test_build_pack_counts_and_sorting():
    p = _pack()
    assert p.counts == {"indicators": 4, "skipped_values": 1, "sigma_total": 1}
    assert [i.value for i in p.iocs["network_traffic"]] == ["198.51.100.1", "198.51.100.7"]
    assert p.techniques[0].sigma_count == 1
    assert p.spl[0].dataset == "network_traffic"
