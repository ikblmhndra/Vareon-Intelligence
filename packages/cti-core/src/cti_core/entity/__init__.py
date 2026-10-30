"""Model entitas P7c: konstanta, normalisasi alias dan id STIX deterministik.

Modul ini sengaja tidak mengimpor model DB supaya bisa dipakai migrasi dan model sekaligus.
"""

from __future__ import annotations

import re
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


# Himpunan spasi eksplisit (bukan str.split()/\\s) supaya Python dan SQL `entity_alias_norm()`
# sepakat: ASCII \t\n\v\f\r + spasi, NBSP, U+1680, U+2000-200B, U+2028/9, U+202F, U+205F,
# U+3000, U+FEFF. Dibangun dengan chr() agar file tetap ASCII.
_WS = re.compile(
    "[\t\n\v\f\r "
    + "".join(chr(c) for c in (0xA0, 0x1680))
    + f"{chr(0x2000)}-{chr(0x200B)}"
    + "".join(chr(c) for c in (0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF))
    + "]+"
)


def collapse_ws(s: str) -> str:
    """Rapatkan spasi (himpunan eksplisit di atas) jadi satu spasi, tanpa mengubah huruf."""
    return _WS.sub(" ", s).strip(" ")


def alias_norm(s: str) -> str:
    """Kembaran SQL: `entity_alias_norm(s)` (alembic/versions/entity_model_sql/resolve.sql)."""
    return collapse_ws(s).lower()


def entity_stix_id(type: str, name: str) -> str:
    return f"{type}--{uuid.uuid5(ENTITY_NAMESPACE, f'{type}:{name.lower()}')}"


def relationship_stix_id(src_stix: str, rel_type: str, dst_stix: str) -> str:
    return f"relationship--{uuid.uuid5(ENTITY_NAMESPACE, f'{src_stix}:{rel_type}:{dst_stix}')}"
