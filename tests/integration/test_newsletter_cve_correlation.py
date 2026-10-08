"""Integration test korelasi CVE di newsletter (`_get_tp_cve_ids` + `_find_cve_mentions`) --
Postgres REAL (testcontainers). `_enrich_articles()` sendiri tidak dites di sini (butuh browser
Playwright dan LLM, lihat `test_newsletter_router_snapshot.py`)."""

from __future__ import annotations

import pytest
from cti_api.services import newsletter as newsletter_service
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_true_positive_cves_are_judged_per_client_row(async_db_session: AsyncSession) -> None:
    """FP itu per `(cve_id, client_id)`. CVE masih true positive selama ada SATU client yang
    men-track-nya tanpa menandai FP. Dulu hanya FP client "default" yang dihitung: artikel yang
    menyebut CVE yang FP di "default" tapi valid di client lain tidak ditandai, dan CVE yang
    di-FP-kan semua client selain "default" tetap ditandai."""
    clients = AsyncClientRepo(async_db_session)
    await clients.ensure_default()
    await clients.create(client_id="acme", name="Acme", countries=[])
    async_db_session.add_all(
        [
            # A: FP di default, acme masih menganggapnya valid -> TP
            CveTracker(cve_id="CVE-2026-0101", client_id="default", tech="nginx"),
            CveTracker(cve_id="CVE-2026-0101", client_id="acme", tech="nginx"),
            # B: hanya acme yang track, tidak ada FP -> TP
            CveTracker(cve_id="CVE-2026-0102", client_id="acme", tech="nginx"),
            # C: FP di kedua client -> bukan TP
            CveTracker(cve_id="CVE-2026-0103", client_id="default", tech="nginx"),
            CveTracker(cve_id="CVE-2026-0103", client_id="acme", tech="nginx"),
            # D: hanya acme yang track dan acme menandainya FP -> bukan TP
            CveTracker(cve_id="CVE-2026-0104", client_id="acme", tech="nginx"),
        ]
    )
    await async_db_session.flush()
    fp = AsyncCveFalsePositiveRepo(async_db_session)
    await fp.mark("CVE-2026-0101", "default")
    await fp.mark("CVE-2026-0103", "default")
    await fp.mark("CVE-2026-0103", "acme")
    await fp.mark("CVE-2026-0104", "acme")

    tp = await newsletter_service._get_tp_cve_ids(async_db_session)
    assert tp == {"CVE-2026-0101", "CVE-2026-0102"}

    title = "Patch CVE-2026-0101, CVE-2026-0103 and CVE-2026-0104 now"
    assert newsletter_service._find_cve_mentions(title, None, tp) == ["CVE-2026-0101"]
