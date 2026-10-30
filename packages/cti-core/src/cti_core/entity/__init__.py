"""Model entitas P7c: konstanta, normalisasi alias dan id STIX deterministik.

Modul ini sengaja tidak mengimpor model DB supaya bisa dipakai migrasi dan model sekaligus.
"""

from __future__ import annotations

import uuid

ENTITY_TYPES = (
    "intrusion-set",
    "malware",
    "tool",
    "attack-pattern",
    "vulnerability",
    "campaign",
    "identity",
    "location",
)
RELATIONSHIP_TYPES = (
    "uses",
    "targets",
    "attributed-to",
    "exploits",
    "indicates",
    "variant-of",
    "located-at",
    "related-to",
    "subtechnique-of",
)
MENTION_METHODS = ("dictionary", "llm", "keyword", "explicit", "analyst", "legacy")
ENTITY_SOURCES = (
    "attack",
    "galaxy",
    "dictionary",
    "analyst",
    "cve",
    "iso",
    "sector",
    "ransomware",
    "legacy",
)
ALIAS_SOURCES = ("attack", "galaxy", "analyst", "legacy", "dictionary")
RELATIONSHIP_PROVENANCES = ("attack", "analyst", "ransomware")

# Dipakai untuk id yang dihitung sekali saat dibuat dan tidak pernah dihitung ulang.
ENTITY_NAMESPACE = uuid.UUID("3c9f4b1e-7a52-5d8e-9b0c-6f1e2d3a4b5c")


def alias_norm(s: str) -> str:
    """Kembaran SQL: `lower(regexp_replace(btrim(s), '\\s+', ' ', 'g'))`."""
    return " ".join(s.lower().split())


def entity_stix_id(type: str, name: str) -> str:
    return f"{type}--{uuid.uuid5(ENTITY_NAMESPACE, f'{type}:{name.lower()}')}"


def relationship_stix_id(src_stix: str, rel_type: str, dst_stix: str) -> str:
    return f"relationship--{uuid.uuid5(ENTITY_NAMESPACE, f'{src_stix}:{rel_type}:{dst_stix}')}"
