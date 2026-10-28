"""Port `decay_sweep()` (`ScraperNewsWeb/app/services/ioc_service.py:303`)
-- Fase 7.8, salah satu dari 5 loop Celery beat.

Recompute confidence+actionability SEMUA IOC yang belum di-refresh dalam
24 jam terakhir (`AsyncIOCRepo.list_needing_decay`) -- "decay" di sini
artinya confidence turun seiring umur IOC (lihat `confidence.
compute_ioc_confidence`), sweep ini yang jaga angkanya tetap ke-update
walau gak ada feedback analis baru masuk.

Beda dari versi lama: Mongo `bulk_write` batch 500 (satu round-trip per
batch), di sini SATU `UPDATE` per-IOC lewat `AsyncIOCRepo.
apply_confidence_and_actionability` (dipanggil `confidence.
recompute_ioc_confidence_and_actionability`, fungsi yang SAMA dipakai
`routers/iocs.py`'s endpoint feedback -- SATU sumber logic recompute,
bukan duplikat). Trade-off sadar: lebih banyak round-trip DB, tapi
lebih konsisten (fungsi yang sama, bukan reimplementasi query update)
dan volume IOC di korpus ini gak masuk kelas "butuh bulk write" (order
ribuan, bukan jutaan)."""

from __future__ import annotations

import datetime
from typing import Any

from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services import confidence

_DECAY_AFTER = datetime.timedelta(hours=24)
_BATCH_SIZE = 500


async def decay_sweep(session: AsyncSession) -> dict[str, Any]:
    now = datetime.datetime.now(datetime.UTC)
    cutoff = now - _DECAY_AFTER
    repo = AsyncIndicatorRepo(session)

    scanned = 0
    updated = 0
    while True:
        batch = await repo.list_needing_decay(cutoff, limit=_BATCH_SIZE)
        if not batch:
            break
        for ioc in batch:
            scanned += 1
            await confidence.recompute_ioc_confidence_and_actionability(session, ioc, now=now)
            updated += 1
        await session.flush()

    return {"scanned": scanned, "updated": updated}
