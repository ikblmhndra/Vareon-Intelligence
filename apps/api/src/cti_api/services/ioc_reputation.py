"""Label reputasi satu baris IOC di reader artikel, dari kartu provider yang sudah tersimpan.

Kartu ditulis `ioc_enrichment` ke `Indicator.enrichment["providers"]` (bentuk di
`ioc_providers`: `key`, `name`, `verdict`). Fungsi ini murni (tanpa DB, tanpa panggilan
provider) supaya endpoint IOC artikel tetap murah: satu label ringkas, bukan seluruh kartu.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Makin kecil makin buruk. `unknown` sengaja tidak ada: provider belum menilai, bukan
# "bersih", jadi tidak boleh menggeser label maupun memunculkannya.
_SEVERITY = {"malicious": 0, "suspicious": 1, "clean": 2}


def reputation_label(enrichment: Mapping[str, Any]) -> str | None:
    """Verdict terburuk lintas kartu sebagai "{verdict} ({nama provider})"; `None` bila tidak
    ada kartu atau semuanya `unknown`. Seri diputus urutan kartu (sudah terurut per `key`)."""
    cards = enrichment.get("providers")
    if not isinstance(cards, list):
        return None
    worst: tuple[int, str, str] | None = None
    for card in cards:
        if not isinstance(card, Mapping):
            continue
        verdict = str(card.get("verdict", ""))
        rank = _SEVERITY.get(verdict)
        if rank is None:
            continue
        if worst is None or rank < worst[0]:
            worst = (rank, verdict, str(card.get("name") or card.get("key") or ""))
    if worst is None:
        return None
    return f"{worst[1]} ({worst[2]})"
