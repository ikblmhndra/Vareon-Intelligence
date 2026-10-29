"""ID STIX deterministik per indikator (P7b): satu rumus untuk kolom `indicators.stix_id`,
ekspor STIX (`cti_api.services.stix._uuid5`) dan server TAXII, supaya `indicator--<uuid>` sama di
mana-mana dan konsumen bisa melacak objek yang sama antar-polling."""

from __future__ import annotations

import uuid


def indicator_uuid(type: str, value: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"{type}:{value}".lower().strip())
