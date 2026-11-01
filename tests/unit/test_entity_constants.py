"""Konstanta model entitas P7c: normalisasi alias, id STIX deterministik, vocab sektor, nama ISO."""

import pathlib

from cti_core.entity import alias_norm, entity_stix_id, relationship_stix_id
from cti_core.entity.countries import ISO_COUNTRY_NAMES
from cti_core.entity.sectors import SECTORS, sector_for_label

_LABELS = pathlib.Path(__file__).parent / "data" / "dev_industry_labels.txt"

# STIX 2.1 `industry-sector-ov`
_STIX_SECTORS = {
    "agriculture", "aerospace", "automotive", "chemical", "commercial", "communications",
    "construction", "defense", "education", "emergency-services", "energy", "entertainment",
    "financial-services", "government", "government-local", "government-national",
    "government-public-services", "government-regional", "healthcare", "hospitality-leisure",
    "infrastructure", "infrastructure-dams", "infrastructure-nuclear", "infrastructure-water",
    "insurance", "manufacturing", "mining", "non-profit", "pharmaceuticals", "retail",
    "technology", "telecommunications", "transportation", "utilities",
}  # fmt: skip


def test_alias_norm() -> None:
    assert alias_norm("  APT  29 ") == "apt 29"


_UNICODE_WS = [0xA0, 0x1680, *range(0x2000, 0x200C), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF]


def test_alias_norm_explicit_unicode_whitespace() -> None:
    for cp in _UNICODE_WS:
        assert alias_norm(f"{chr(cp)}APT{chr(cp)}{chr(cp)}29{chr(cp)}") == "apt 29", hex(cp)
    assert alias_norm("a\t\n\v\f\r b") == "a b"


def test_stix_ids_stable() -> None:
    a = entity_stix_id("intrusion-set", "APT29")
    assert a == entity_stix_id("intrusion-set", "apt29")
    assert a.startswith("intrusion-set--")
    assert a != entity_stix_id("malware", "APT29")
    r = relationship_stix_id(a, "uses", "malware--x")
    assert r == relationship_stix_id(a, "uses", "malware--x")
    assert r.startswith("relationship--")


def test_every_dev_industry_label_mapped() -> None:
    labels = [x for x in _LABELS.read_text().splitlines() if x]
    assert len(labels) == 28
    for label in labels:
        got = sector_for_label(label)
        if label == "General":
            assert got is None
        else:
            assert got in SECTORS, label


def test_sectors_are_stix_vocab() -> None:
    assert set(SECTORS) <= _STIX_SECTORS


def test_iso_names() -> None:
    assert ISO_COUNTRY_NAMES["ID"] == "Indonesia"
    assert len(ISO_COUNTRY_NAMES) == 249


def test_label_to_sector_public_mapping() -> None:
    from cti_core.entity.sectors import label_to_sector

    mapping = label_to_sector()
    assert "General" not in mapping  # tanpa sektor
    assert mapping["Cloud Services"] == "technology"
    assert set(mapping.values()) <= set(SECTORS)
    assert all(sector_for_label(k) == v for k, v in mapping.items())
