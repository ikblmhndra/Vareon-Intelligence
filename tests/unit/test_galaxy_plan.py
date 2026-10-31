"""Perencana merge alias MISP Galaxy (spec 4.2) di atas state entitas di memori.

Yang dijaga (risiko R1): cluster yang menyentuh dua entitas ATT&CK dilewati, sinonim ambigu /
satu kata umum tidak pernah menyebabkan merge, alias milik ATT&CK/analis tidak dipindah, target
= entitas ATT&CK kalau tepat satu, selain itu entitas dengan mention terbanyak."""

from __future__ import annotations

import json
import pathlib

import pytest
from cti_core.entity.galaxy import (
    GALAXY_FILES,
    GalaxyPlan,
    GalaxyState,
    build_plan,
    load_galaxy,
    shared_norms,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]
MINI = ROOT / "tests" / "fixtures" / "galaxy" / "mini-threat-actor.json"
SNAPSHOT = ROOT / "packages" / "cti-core" / "src" / "cti_core" / "entity" / "data" / "misp-galaxy"
IS = "intrusion-set"


def _state() -> GalaxyState:
    st = GalaxyState()
    st.add_entity(1, IS, "APT29", source="attack", mentions=10, aliases=[("Cozy Bear", "attack")])
    st.add_entity(2, IS, "Cloaked Ursa", source="dictionary", mentions=3)
    st.add_entity(3, IS, "Lazarus Group", source="attack", mentions=1)
    st.add_entity(4, IS, "Kimsuky", source="attack", mentions=1)
    st.add_entity(5, IS, "0ktapus", source="dictionary", mentions=5)
    st.add_entity(6, IS, "Muddled Libra", source="dictionary", mentions=2)
    st.add_entity(7, IS, "Mustang Panda", source="dictionary", mentions=4)
    # lebih banyak mention dari Mustang Panda: tetap tidak boleh jadi target lewat "basin"
    st.add_entity(8, IS, "Basin", source="dictionary", mentions=9)
    st.add_entity(9, IS, "Turla", source="attack", mentions=1)
    st.add_entity(
        10,
        IS,
        "Venom Cluster",
        source="analyst",
        mentions=7,
        aliases=[("Venomous Bear", "analyst")],
    )
    return st


def _plan() -> GalaxyPlan:
    clusters = load_galaxy("threat-actor", json.loads(MINI.read_text()))
    return build_plan(_state(), clusters)


def _merges(plan: GalaxyPlan) -> set[tuple[int | None, int | None]]:
    return {(m.source_id, m.target_id) for m in plan.merges}


def _aliases(plan: GalaxyPlan, cluster: str) -> dict[str, str]:
    return {a.alias: a.target_name for a in plan.new_aliases if a.cluster == cluster}


def test_load_galaxy_reads_value_and_synonyms() -> None:
    clusters = load_galaxy("threat-actor", json.loads(MINI.read_text()))
    by_value = {c.value: c for c in clusters}
    assert by_value["APT29"].synonyms == ["Cozy Bear", "Nobelium", "Cloaked Ursa"]
    assert by_value["APT29"].kind == "actor"
    assert by_value["No Synonyms Here"].synonyms == []


def test_load_galaxy_rejects_bad_schema() -> None:
    with pytest.raises(ValueError):
        load_galaxy("threat-actor", {"name": "x"})
    with pytest.raises(ValueError):
        load_galaxy("unknown-galaxy", {"values": []})


def test_two_attack_cluster_skipped() -> None:
    plan = _plan()
    skips = [s for s in plan.skips if s.cluster == "Lazarus Group"]
    assert {s.reason for s in skips} == {"two_attack"}
    assert {s.entity_id for s in skips} == {3, 4}
    assert not [m for m in plan.merges if m.cluster == "Lazarus Group"]
    assert _aliases(plan, "Lazarus Group") == {}  # "Hidden Cobra" juga tidak ditambahkan


def test_ambiguous_synonym_never_merges() -> None:
    plan = _plan()
    assert all(8 not in pair for pair in _merges(plan))
    skip = [s for s in plan.skips if s.cluster == "Mustang Panda"]
    assert [(s.reason, s.alias, s.entity_id) for s in skip] == [("ambiguous", "Basin", 8)]
    assert _aliases(plan, "Mustang Panda") == {"Bronze President": "Mustang Panda"}


def test_target_is_attack_entity() -> None:
    plan = _plan()
    assert (2, 1) in _merges(plan)
    assert _aliases(plan, "APT29") == {"Nobelium": "APT29"}  # "Cozy Bear" sudah milik APT29


def test_target_most_mentions_without_attack() -> None:
    plan = _plan()
    assert (6, 5) in _merges(plan)
    assert _aliases(plan, "Scattered Spider") == {
        "Scattered Spider": "0ktapus",
        "Octo Tempest": "0ktapus",
    }


def test_owned_alias_not_moved() -> None:
    plan = _plan()
    assert all(10 not in pair for pair in _merges(plan))
    skip = [s for s in plan.skips if s.cluster == "Turla"]
    assert [(s.reason, s.alias, s.entity_id) for s in skip] == [("owned", "Venomous Bear", 10)]
    # sinonim satu kata yang belum dimiliki siapa pun boleh jadi alias (tak memicu merge)
    assert _aliases(plan, "Turla") == {"Snake": "Turla"}


def test_cluster_without_entity_creates_nothing() -> None:
    """Ruling 19: cluster tanpa entitas tidak menambah entitas maupun alias."""
    plan = _plan()
    for cluster in ("Brand New Crew", "No Synonyms Here"):
        assert [a for a in plan.new_aliases if a.cluster == cluster] == []
        assert [s for s in plan.skips if s.cluster == cluster] == []


def test_empty_state_plans_nothing_on_full_snapshot() -> None:
    clusters = [
        c
        for name in GALAXY_FILES
        for c in load_galaxy(name, json.loads((SNAPSHOT / f"{name}.json").read_text()))
    ]
    plan = build_plan(GalaxyState(), clusters)
    assert plan.merges == [] and plan.new_aliases == [] and plan.skips == []


def test_merges_are_exactly_expected() -> None:
    assert _merges(_plan()) == {(2, 1), (6, 5)}


def test_undone_pair_skipped() -> None:
    st = _state()
    st.undone_pairs.add(frozenset({2, 1}))
    clusters = load_galaxy("threat-actor", json.loads(MINI.read_text()))
    plan = build_plan(st, clusters)
    assert (2, 1) not in _merges(plan)
    assert [(s.reason, s.entity_id) for s in plan.skips if s.cluster == "APT29"] == [("undone", 2)]


def _cluster(uuid: str, value: str, *synonyms: str) -> dict[str, object]:
    return {"uuid": uuid, "value": value, "meta": {"synonyms": list(synonyms)}}


def test_shared_synonym_does_not_chain_two_clusters() -> None:
    """Review Task 7 (R1): cluster A menambah "Cobalt Gypsy" ke targetnya, cluster B lalu
    me-merge entitasnya ke target A lewat sinonim itu. Norm bersama tidak pernah menjangkar
    merge dan tidak ditambahkan sebagai alias."""
    st = GalaxyState()
    st.add_entity(1, IS, "Cleaver Crew", source="dictionary", mentions=3)
    st.add_entity(2, IS, "Oil Rig Ops", source="dictionary", mentions=1)
    content = {
        "values": [
            _cluster("a", "Cleaver Crew", "Cobalt Gypsy"),
            _cluster("b", "Oil Rig Ops", "Cobalt Gypsy"),
        ]
    }
    plan = build_plan(st, load_galaxy("threat-actor", content))
    assert plan.merges == []
    assert plan.new_aliases == []
    assert [(k.cluster, k.reason, k.alias) for k in plan.skips] == [
        ("Cleaver Crew", "ambiguous", "Cobalt Gypsy"),
        ("Oil Rig Ops", "ambiguous", "Cobalt Gypsy"),
    ]


def test_shared_synonym_owned_by_third_entity_never_merges() -> None:
    st = GalaxyState()
    st.add_entity(1, IS, "Cleaver Crew", source="dictionary", mentions=3)
    st.add_entity(2, IS, "Oil Rig Ops", source="dictionary", mentions=1)
    st.add_entity(3, IS, "Cobalt Gypsy", source="dictionary", mentions=9)
    content = {
        "values": [
            _cluster("a", "Cleaver Crew", "Cobalt Gypsy"),
            _cluster("b", "Oil Rig Ops", "Cobalt Gypsy"),
        ]
    }
    plan = build_plan(st, load_galaxy("threat-actor", content))
    assert plan.merges == []
    assert {(k.reason, k.entity_id) for k in plan.skips} == {("ambiguous", 3)}


def test_galaxy_alias_never_anchors_across_runs() -> None:
    """Run sebelumnya (cluster lain) menambahkan "Cobalt Gypsy" sebagai alias galaxy ke Cleaver
    Crew; run ini hanya melihat cluster B, jadi norm itu tidak terdeteksi bersama. Alias galaxy
    tetap tidak boleh menjangkar merge."""
    st = GalaxyState()
    st.add_entity(
        1, IS, "Cleaver Crew", source="dictionary", mentions=3,
        aliases=[("Cobalt Gypsy", "galaxy")],
    )  # fmt: skip
    st.add_entity(2, IS, "Oil Rig Ops", source="dictionary", mentions=1)
    content = {"values": [_cluster("b", "Oil Rig Ops", "Cobalt Gypsy", "Twisted Kitten")]}
    plan = build_plan(st, load_galaxy("threat-actor", content))
    assert plan.merges == []
    assert [(k.reason, k.entity_id) for k in plan.skips] == [("owned", 1)]
    assert [(a.alias, a.target_id) for a in plan.new_aliases] == [("Twisted Kitten", 2)]


def test_two_attack_counts_risky_attack_owner() -> None:
    st = GalaxyState()
    st.add_entity(1, IS, "APT29", source="attack")
    st.add_entity(2, IS, "Cobalt Group", source="attack", aliases=[("Cobalt", "attack")])
    content = {"values": [_cluster("x", "APT29", "Cobalt")]}  # "cobalt" ada di AMBIGUOUS
    plan = build_plan(st, load_galaxy("threat-actor", content))
    assert {(k.reason, k.entity_id) for k in plan.skips} == {("two_attack", 1), ("two_attack", 2)}
    assert plan.merges == [] and plan.new_aliases == []


def test_attack_curated_scoped_to_cluster_types() -> None:
    """ "Snake" adalah alias software ATT&CK (malware), bukan nama grup: di cluster aktor ia tetap
    satu kata umum, jadi entitas aktor "Snake" tidak di-merge."""
    st = GalaxyState()
    st.add_entity(1, IS, "Turla", source="attack")
    st.add_entity(2, IS, "Snake", source="dictionary", mentions=4)
    st.add_entity(3, "malware", "Uroburos", source="attack", aliases=[("Snake", "attack")])
    content = {"values": [_cluster("t", "Turla", "Snake")]}
    plan = build_plan(st, load_galaxy("threat-actor", content))
    assert plan.merges == []
    assert [(k.reason, k.entity_id) for k in plan.skips] == [("ambiguous", 2)]


def test_attack_norms_only_for_new_alias_rows() -> None:
    st = GalaxyState()
    st.add_entity(1, IS, "Foo Crew", source="dictionary")
    st.add_alias(IS, "Foo Crew", 2, "attack")  # (tipe, norm) sudah ada: diabaikan
    assert "foo crew" not in st.attack_norms
    assert st.aliases[(IS, "foo crew")].entity_id == 1
    st.add_entity(3, IS, "Bar Crew", source="attack")
    st.add_alias(IS, "Bar Crew", 3, "attack")  # baris yang sama lagi: tidak dicatat dua kali
    assert len(st.attack_norms["bar crew"]) == 1


def test_shared_norms_on_real_snapshot() -> None:
    clusters = [
        c
        for name in GALAXY_FILES
        for c in load_galaxy(name, json.loads((SNAPSHOT / f"{name}.json").read_text()))
    ]
    shared = shared_norms(clusters)
    assert len(shared["actor"]) > 50 and len(shared["malware"]) > 30


def test_repo_snapshot_parses() -> None:
    for name, kind in GALAXY_FILES.items():
        clusters = load_galaxy(name, json.loads((SNAPSHOT / f"{name}.json").read_text()))
        assert len(clusters) > 1000
        assert {c.kind for c in clusters} == {kind}
    source = (SNAPSHOT / "SOURCE").read_text()
    assert "CC0" in source
    assert "commit" in source


def test_ambiguous_constants_reexported_from_enrich() -> None:
    from cti_core.entity import ambiguous
    from cti_enrich.tier1 import entities

    assert entities.AMBIGUOUS is ambiguous.AMBIGUOUS
    assert entities.WINDOWS_UTILITY_NAMES is ambiguous.WINDOWS_UTILITY_NAMES
