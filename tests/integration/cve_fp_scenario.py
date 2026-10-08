"""Skenario seed bersama untuk test yang mendefinisikan "true positive" per baris client.

FP itu per `(cve_id, client_id)`: CVE masih true positive selama ada SATU client yang men-track-nya
tanpa menandainya FP. Dipakai `test_cve_lookup_service.py` (enrichment KEV/EPSS/exploit-db) dan
`test_newsletter_cve_correlation.py`, yang memakai definisi yang sama
(`AsyncCveTrackerRepo.list_true_positive_cve_ids`)."""

from __future__ import annotations

from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from sqlalchemy.ext.asyncio import AsyncSession

FP_IN_DEFAULT_ONLY = "CVE-2026-0101"
"""Di-track `default` dan `acme`, FP hanya di `default`. Acme masih menganggapnya valid -> TP."""

ONLY_IN_ACME = "CVE-2026-0102"
"""Hanya acme yang men-track, tanpa FP -> TP."""

FP_IN_BOTH = "CVE-2026-0103"
"""Di-track `default` dan `acme`, FP di keduanya -> bukan TP."""

FP_IN_ITS_ONLY_CLIENT = "CVE-2026-0104"
"""Hanya acme yang men-track dan acme menandainya FP -> bukan TP (dulu lolos: yang dilihat hanya FP
milik `default`)."""

TRUE_POSITIVES = [FP_IN_DEFAULT_ONLY, ONLY_IN_ACME]
"""Terurut, supaya bisa dibandingkan langsung dengan `sorted(...)`."""

_TRACKED = [
    (FP_IN_DEFAULT_ONLY, "default"),
    (FP_IN_DEFAULT_ONLY, "acme"),
    (ONLY_IN_ACME, "acme"),
    (FP_IN_BOTH, "default"),
    (FP_IN_BOTH, "acme"),
    (FP_IN_ITS_ONLY_CLIENT, "acme"),
]
_MARKED_FP = [
    (FP_IN_DEFAULT_ONLY, "default"),
    (FP_IN_BOTH, "default"),
    (FP_IN_BOTH, "acme"),
    (FP_IN_ITS_ONLY_CLIENT, "acme"),
]


async def seed_per_client_false_positives(session: AsyncSession) -> None:
    """Dua client (`default`, `acme`), empat CVE, dan penanda FP seperti di konstanta di atas."""
    clients = AsyncClientRepo(session)
    await clients.ensure_default()
    await clients.create(client_id="acme", name="Acme", countries=[])
    session.add_all(CveTracker(cve_id=c, client_id=cl, tech="nginx") for c, cl in _TRACKED)
    await session.flush()
    fp = AsyncCveFalsePositiveRepo(session)
    for cve_id, client_id in _MARKED_FP:
        await fp.mark(cve_id, client_id)
