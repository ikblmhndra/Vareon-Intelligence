"""Builder STIX dari baris entitas/relasi/story (P7c Task 14): id dan waktu dari baris, jadi dua
pemanggilan identik; tombstone/suppressed terbit `revoked` dengan properti wajib saja."""

from __future__ import annotations

import datetime
from typing import Any

from cti_api.services.stix import (
    TLP_MARKING_IDS,
    entity_to_stix,
    relationship_to_stix,
    story_to_report,
)
from cti_core.db.models.entity import Entity, EntityAlias, Relationship
from cti_core.db.models.story import Story
from cti_core.entity import entity_stix_id, relationship_stix_id

_CREATED = datetime.datetime(2026, 10, 1, 1, 2, 3, 456789, tzinfo=datetime.UTC)
_CHANGED = datetime.datetime(2026, 10, 29, 4, 0, 25, 542000, tzinfo=datetime.UTC)


def _ent(type_: str, name: str, *aliases: str, **kw: Any) -> Entity:
    e = Entity(
        type=type_,
        stix_id=kw.pop("stix_id", entity_stix_id(type_, name)),
        name=name,
        source=kw.pop("source", "analyst"),
        suppressed=kw.pop("suppressed", False),
        tlp=kw.pop("tlp", "clear"),
        created_at=_CREATED,
        feed_changed_at=_CHANGED,
        **kw,
    )
    for a in aliases:
        e.aliases.append(EntityAlias(alias=a, alias_norm=a.lower(), source="analyst"))
    return e


def _common(obj: dict[str, Any], e: Entity) -> None:
    assert obj["type"] == e.type
    assert obj["id"] == e.stix_id
    assert obj["spec_version"] == "2.1"
    assert obj["created"] == "2026-10-01T01:02:03.456Z"
    assert obj["modified"] == "2026-10-29T04:00:25.542Z"
    assert obj["object_marking_refs"] == [TLP_MARKING_IDS[e.tlp]]
    assert "confidence" not in obj


def test_intrusion_set_aliases_exclude_name_sorted() -> None:
    e = _ent(
        "intrusion-set",
        "APT41",
        "APT41",
        "Wicked Panda",
        "Barium",
        description="Grup China.",
        source="attack",
        external_id="G0096",
        tlp="amber",
    )
    obj = entity_to_stix(e)
    _common(obj, e)
    assert obj["name"] == "APT41"
    assert obj["description"] == "Grup China."
    assert obj["aliases"] == ["Barium", "Wicked Panda"]
    assert obj["external_references"] == [
        {
            "source_name": "mitre-attack",
            "external_id": "G0096",
            "url": "https://attack.mitre.org/groups/G0096/",
        }
    ]
    assert entity_to_stix(e) == obj


def test_no_aliases_key_when_only_own_name() -> None:
    obj = entity_to_stix(_ent("intrusion-set", "Lazarus", "Lazarus"))
    assert "aliases" not in obj
    assert "external_references" not in obj


def test_malware_is_family_and_tool_has_no_is_family() -> None:
    mal = entity_to_stix(_ent("malware", "ShadowPad", "ShadowPad", "POISONPLUG"))
    assert mal["is_family"] is True
    assert mal["aliases"] == ["POISONPLUG"]
    tool = entity_to_stix(
        _ent("tool", "Mimikatz", "Mimikatz", source="attack", external_id="S0002")
    )
    assert "is_family" not in tool
    assert tool["external_references"][0]["url"] == "https://attack.mitre.org/software/S0002/"


def test_attack_pattern_external_reference_and_no_aliases() -> None:
    e = _ent("attack-pattern", "Spearphishing Attachment", "T1566.001", source="attack")
    e.external_id = "T1566.001"
    obj = entity_to_stix(e)
    _common(obj, e)
    assert obj["name"] == "Spearphishing Attachment"
    assert "aliases" not in obj
    assert obj["external_references"] == [
        {
            "source_name": "mitre-attack",
            "external_id": "T1566.001",
            "url": "https://attack.mitre.org/techniques/T1566/001/",
        }
    ]


def test_campaign_requires_name_and_takes_aliases() -> None:
    obj = entity_to_stix(_ent("campaign", "Operation X", "Operation X", "OpX"))
    assert obj["type"] == "campaign"
    assert obj["name"] == "Operation X"
    assert obj["aliases"] == ["OpX"]


def test_vulnerability_cve_reference() -> None:
    obj = entity_to_stix(
        _ent("vulnerability", "CVE-2024-3400", source="cve", external_id="CVE-2024-3400")
    )
    assert obj["external_references"] == [{"source_name": "cve", "external_id": "CVE-2024-3400"}]


def test_sector_identity_class() -> None:
    obj = entity_to_stix(
        _ent(
            "identity",
            "Financial Services",
            source="sector",
            identity_class="class",
            external_id="financial-services",
        )
    )
    assert obj["identity_class"] == "class"
    assert obj["sectors"] == ["financial-services"]
    assert obj["name"] == "Financial Services"


def test_victim_identity_is_organization_without_sectors() -> None:
    obj = entity_to_stix(_ent("identity", "Acme Corp", identity_class="organization"))
    assert obj["identity_class"] == "organization"
    assert "sectors" not in obj


def test_location_country() -> None:
    obj = entity_to_stix(_ent("location", "Indonesia", source="iso", external_id="ID"))
    assert obj["type"] == "location"
    assert obj["country"] == "ID"
    assert obj["name"] == "Indonesia"


def test_suppressed_and_tombstone_are_revoked_with_required_only() -> None:
    for kw in ({"suppressed": True}, {"merged_into_id": 7}):
        obj = entity_to_stix(
            _ent("malware", "Noise", "Noise", "N1", description="x", external_id="S1", **kw)
        )
        assert obj["revoked"] is True
        assert obj["is_family"] is True
        assert obj["name"] == "Noise"
        for dropped in ("description", "aliases", "external_references"):
            assert dropped not in obj


def test_revoked_keeps_type_specific_required_properties() -> None:
    sector = entity_to_stix(
        _ent("identity", "Energy", identity_class="class", external_id="energy", suppressed=True)
    )
    assert sector["identity_class"] == "class"
    loc = entity_to_stix(_ent("location", "Indonesia", external_id="ID", merged_into_id=3))
    assert loc["country"] == "ID"


def _rel(**kw: Any) -> Relationship:
    src, dst = entity_stix_id("intrusion-set", "a"), entity_stix_id("malware", "b")
    base: dict[str, Any] = {
        "stix_id": relationship_stix_id(src, "uses", dst),
        "relationship_type": "uses",
        "confidence": 85,
        "tlp": "green",
        "created_at": _CREATED,
        "feed_changed_at": _CHANGED,
    }
    base.update(kw)
    return Relationship(**base)


def test_relationship_uses_row_id_and_confidence() -> None:
    src, dst = entity_stix_id("intrusion-set", "a"), entity_stix_id("malware", "b")
    r = _rel(
        first_seen=_CREATED,
        last_seen=_CHANGED,
        description="Dipakai.",
    )
    obj = relationship_to_stix(r, src, dst)
    assert obj["type"] == "relationship"
    assert obj["id"] == r.stix_id
    assert obj["spec_version"] == "2.1"
    assert obj["relationship_type"] == "uses"
    assert obj["source_ref"] == src
    assert obj["target_ref"] == dst
    assert obj["confidence"] == 85
    assert obj["start_time"] == "2026-10-01T01:02:03.456Z"
    assert obj["stop_time"] == "2026-10-29T04:00:25.542Z"
    assert obj["description"] == "Dipakai."
    assert obj["created"] == "2026-10-01T01:02:03.456Z"
    assert obj["modified"] == "2026-10-29T04:00:25.542Z"
    assert obj["object_marking_refs"] == [TLP_MARKING_IDS["green"]]
    assert "revoked" not in obj


def test_relationship_minimal_and_revoked() -> None:
    src, dst = entity_stix_id("intrusion-set", "a"), entity_stix_id("malware", "b")
    obj = relationship_to_stix(_rel(confidence=None, revoked_at=_CHANGED), src, dst)
    assert obj["revoked"] is True
    for absent in ("confidence", "start_time", "stop_time", "description"):
        assert absent not in obj


def _story(**kw: Any) -> Story:
    base: dict[str, Any] = {
        "id": 12,
        "title": "APT41 menyerang",
        "first_seen_at": _CREATED,
        "created_at": _CREATED,
        "feed_changed_at": _CHANGED,
    }
    base.update(kw)
    return Story(**base)


def test_report_none_without_refs() -> None:
    assert story_to_report(_story(), [], ["https://a.example/x"]) is None


def test_report_sorts_dedups_and_shapes() -> None:
    refs = ["malware--b", "intrusion-set--a", "malware--b"]
    obj = story_to_report(
        _story(), refs, ["https://b.example", "https://a.example", "https://b.example"]
    )
    assert obj is not None
    assert obj["type"] == "report"
    assert obj["id"].startswith("report--")
    assert obj["id"] == story_to_report(_story(), refs, [])["id"]  # type: ignore[index]
    assert obj["name"] == "APT41 menyerang"
    assert obj["published"] == "2026-10-01T01:02:03.456Z"
    assert obj["created"] == "2026-10-01T01:02:03.456Z"
    assert obj["modified"] == "2026-10-29T04:00:25.542Z"
    assert obj["report_types"] == ["threat-report"]
    assert obj["object_refs"] == ["intrusion-set--a", "malware--b"]
    assert [x["url"] for x in obj["external_references"]] == [
        "https://a.example",
        "https://b.example",
    ]
    assert all(x["source_name"] for x in obj["external_references"])


def test_report_without_urls_has_no_external_references() -> None:
    obj = story_to_report(_story(), ["malware--b"], [])
    assert obj is not None
    assert "external_references" not in obj


def test_stop_time_only_when_after_start_time() -> None:
    src, dst = entity_stix_id("intrusion-set", "a"), entity_stix_id("malware", "b")
    equal = relationship_to_stix(_rel(first_seen=_CHANGED, last_seen=_CHANGED), src, dst)
    assert "start_time" in equal and "stop_time" not in equal
    reversed_ = relationship_to_stix(_rel(first_seen=_CHANGED, last_seen=_CREATED), src, dst)
    assert "stop_time" not in reversed_
    only_last = relationship_to_stix(_rel(last_seen=_CHANGED), src, dst)
    assert only_last["stop_time"] == "2026-10-29T04:00:25.542Z"


def test_report_has_clear_marking() -> None:
    obj = story_to_report(_story(), ["malware--b"], [])
    assert obj is not None
    assert obj["object_marking_refs"] == [TLP_MARKING_IDS["clear"]]


def test_location_without_country_code_is_skipped() -> None:
    assert entity_to_stix(_ent("location", "Nowhere")) is None
    assert entity_to_stix(_ent("location", "Nowhere", external_id="", suppressed=True)) is None
