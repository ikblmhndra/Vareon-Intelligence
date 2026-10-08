"""Integration test korelasi CVE di newsletter (`_get_tp_cve_ids` + `_find_cve_mentions`) --
Postgres REAL (testcontainers). `_enrich_articles()` sendiri tidak dites di sini (butuh browser
Playwright dan LLM, lihat `test_newsletter_router_snapshot.py`)."""

from __future__ import annotations

import pytest
from cti_api.services import newsletter as newsletter_service
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.cve_fp_scenario import (
    FP_IN_BOTH,
    FP_IN_DEFAULT_ONLY,
    FP_IN_ITS_ONLY_CLIENT,
    TRUE_POSITIVES,
    seed_per_client_false_positives,
)

pytestmark = pytest.mark.asyncio


async def test_true_positive_cves_are_judged_per_client_row(async_db_session: AsyncSession) -> None:
    """FP itu per `(cve_id, client_id)`. CVE masih true positive selama ada SATU client yang
    men-track-nya tanpa menandai FP. Dulu hanya FP client "default" yang dihitung: artikel yang
    menyebut CVE yang FP di "default" tapi valid di client lain tidak ditandai, dan CVE yang
    di-FP-kan semua client selain "default" tetap ditandai. Skenarionya: `cve_fp_scenario`."""
    await seed_per_client_false_positives(async_db_session)

    tp = await newsletter_service._get_tp_cve_ids(async_db_session)
    assert tp == set(TRUE_POSITIVES)

    title = f"Patch {FP_IN_DEFAULT_ONLY}, {FP_IN_BOTH} and {FP_IN_ITS_ONLY_CLIENT} now"
    assert newsletter_service._find_cve_mentions(title, None, tp) == [FP_IN_DEFAULT_ONLY]
