"""ID STIX deterministik per indikator (P7b): satu rumus untuk kolom `indicators.stix_id` dan
server TAXII, supaya `indicator--<uuid>` stabil antar-polling.

Sengaja TANPA lower()/strip(): keunikan indikator adalah `(type, value)` yang peka huruf besar,
jadi UUID unik by construction (path URL berbeda hanya di huruf besar tetap dua baris). Ini
berbeda dari `cti_api.services.stix._uuid5` untuk nilai bercampur huruf; Task 4 memindahkan id
indikator ekspor STIX ke fungsi ini. Backfill migrasi `machine_api` bergantung pada rumus ini:
mengubahnya kelak butuh migrasi data."""

from __future__ import annotations

import uuid


def indicator_uuid(type: str, value: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"{type}:{value}")
