"""Resolver nama aktor ke bentuk simpan kanonik + penggantian daftar aktor PIR (pure, tanpa DB)."""

from __future__ import annotations

from cti_enrich.backfill_tier1 import canonical_actor_name
from cti_enrich.canonicalise_actors import canonicalise_name_list
from cti_enrich.tier1.dictionary import EntityDictionary, build_dictionary


def _dictionary() -> EntityDictionary:
    return build_dictionary(
        [("APT29", ["Midnight Blizzard", "NOBELIUM"]), ("Lazarus Group", ["Lazarus"])],
        [("Qilin", "malware", [])],
        ["kimsuky"],
        [],
    )


def test_alias_resolves_to_stored_canonical():
    assert canonical_actor_name("Midnight blizzard", _dictionary()) == "Apt29"
    assert canonical_actor_name("Lazarus", _dictionary()) == "Lazarus group"


def test_uppercase_alias_key_is_found_from_stored_form():
    # "NOBELIUM" key-nya case-sensitive; bentuk simpan "Nobelium" dicoba lewat upper().
    assert canonical_actor_name("Nobelium", _dictionary()) == "Apt29"


def test_canonical_name_resolves_to_itself():
    assert canonical_actor_name("Apt29", _dictionary()) == "Apt29"


def test_unknown_and_non_actor_names_are_not_resolved():
    assert canonical_actor_name("Some new crew", _dictionary()) is None
    assert canonical_actor_name("Qilin", _dictionary()) is None


def test_ta_group_name_resolves_to_its_stored_form():
    assert canonical_actor_name("kimsuky", _dictionary()) == "Kimsuky"


def test_name_list_replaces_aliases_and_dedupes_keeping_order():
    names = ["Shinyhunters", "midnight blizzard", "Apt29", "Lazarus"]
    assert canonicalise_name_list(names, _dictionary()) == [
        "Shinyhunters",
        "Apt29",
        "Lazarus group",
    ]


def test_name_list_without_aliases_is_unchanged():
    # Beda huruf besar saja bukan alias: pencocokan di mana-mana case-insensitive.
    names = ["Shinyhunters", "unknown", "kimsuky"]
    assert canonicalise_name_list(names, _dictionary()) == names
