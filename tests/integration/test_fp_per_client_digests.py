"""FP dinilai per baris client di digest GLOBAL: recap, exec dashboard, dan crossref.

`cve_false_positives` berkunci `(cve_id, client_id)`: baris `cve_tracker` baru "false positive"
kalau CLIENT PEMILIK barisnya yang menandainya (definisi yang sama dengan
`list_true_positive_cve_ids`). Ketiga digest ini tak punya konsep client dan dulu memakai himpunan
FP dari client MANA PUN: satu client yang menandai FP menyembunyikan CVE itu dari baris client lain
yang masih membutuhkannya, bahkan bila client penanda tidak men-track CVE-nya sama sekali.
Skenarionya: `cve_fp_scenario`. Monitor PoC GitHub (`reference_data`):
`test_reference_data_true_positive.py`."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services import crossref as crossref_service
from cti_api.services import exec_dashboard as exec_dashboard_service
from cti_api.services import recap as recap_service
from cti_core.db.models.cve import CveThreatActor, CveTracker
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.cve_fp_scenario import (
    FP_IN_BOTH,
    FP_IN_DEFAULT_ONLY,
    FP_IN_ITS_ONLY_CLIENT,
    ONLY_IN_ACME,
    TRUE_POSITIVES,
    seed_per_client_false_positives,
)

pytestmark = pytest.mark.asyncio

DAY = datetime.date(2026, 3, 1)
MARKED_BY_A_CLIENT_THAT_DOES_NOT_TRACK_IT = "CVE-2026-0105"
"""Hanya acme yang men-track; `default` (yang tidak men-track-nya) menandainya FP."""


async def _publish_all_on_day(session: AsyncSession) -> None:
    """Recap mengumpulkan CVE menurut tanggal; tanggal tetap menghindari jam dinding."""
    await session.execute(update(CveTracker).values(published=DAY))
    await session.flush()


async def test_recap_cves_hide_only_rows_the_owning_client_marked_false_positive(
    async_db_session: AsyncSession,
) -> None:
    await seed_per_client_false_positives(async_db_session)
    await _publish_all_on_day(async_db_session)

    cves = await recap_service._collect_cves(async_db_session, DAY)

    assert sorted((c.cve_id, c.client_id) for c in cves) == [
        (FP_IN_DEFAULT_ONLY, "acme"),  # baris default di-FP, baris acme masih valid
        (ONLY_IN_ACME, "acme"),
    ]


async def test_false_positive_of_a_client_that_does_not_track_the_cve_hides_nothing(
    async_db_session: AsyncSession,
) -> None:
    cve_id = MARKED_BY_A_CLIENT_THAT_DOES_NOT_TRACK_IT
    await seed_per_client_false_positives(async_db_session)
    async_db_session.add(CveTracker(cve_id=cve_id, client_id="acme", tech="nginx"))
    await AsyncCveFalsePositiveRepo(async_db_session).mark(cve_id, "default")
    await _publish_all_on_day(async_db_session)

    cves = await recap_service._collect_cves(async_db_session, DAY)

    assert (cve_id, "acme") in {(c.cve_id, c.client_id) for c in cves}


async def test_exec_dashboard_cve_exposure_counts_rows_not_marked_by_their_own_client(
    async_db_session: AsyncSession,
) -> None:
    await seed_per_client_false_positives(async_db_session)

    result = await exec_dashboard_service.get_exec_dashboard(async_db_session, days=90)

    nginx = next(r for r in result["cve_exposure"] if r["tech"] == "nginx")
    assert nginx["total"] == len(TRUE_POSITIVES)


async def test_exec_dashboard_v2_cve_exposure_counts_rows_not_marked_by_their_own_client(
    async_db_session: AsyncSession,
) -> None:
    await seed_per_client_false_positives(async_db_session)

    result = await exec_dashboard_service.get_exec_dashboard_v2(
        async_db_session, days=90, client_id="default", role="soc"
    )

    nginx = next(r for r in result["cve_exposure_v2"] if r["tech"] == "nginx")
    assert nginx["total"] == len(TRUE_POSITIVES)


async def test_crossref_cve_is_rejected_only_when_every_owning_client_marked_it(
    async_db_session: AsyncSession,
) -> None:
    await seed_per_client_false_positives(async_db_session)

    rejected = {
        cve_id: "error" in await crossref_service.get_cve_crossrefs(async_db_session, cve_id)
        for cve_id in (FP_IN_DEFAULT_ONLY, ONLY_IN_ACME, FP_IN_BOTH, FP_IN_ITS_ONLY_CLIENT)
    }

    assert rejected == {
        FP_IN_DEFAULT_ONLY: False,
        ONLY_IN_ACME: False,
        FP_IN_BOTH: True,
        FP_IN_ITS_ONLY_CLIENT: True,
    }


async def test_crossref_cve_describes_the_valid_row_not_the_one_marked_false_positive(
    async_db_session: AsyncSession,
) -> None:
    await seed_per_client_false_positives(async_db_session)
    # Yang diubah baris acme (valid). UPDATE memindahkan baris ke akhir heap, jadi baris default
    # (di-FP) tetap yang pertama dibaca kalau FP tak disaring: tanpa saringan tes ini gagal.
    valid_row = (CveTracker.cve_id == FP_IN_DEFAULT_ONLY) & (CveTracker.client_id == "acme")
    await async_db_session.execute(update(CveTracker).where(valid_row).values(tech="valid-row"))

    result = await crossref_service.get_cve_crossrefs(async_db_session, FP_IN_DEFAULT_ONLY)

    assert result["tech"] == "valid-row"


async def test_crossref_pir_matches_only_rows_not_marked_by_their_own_client(
    async_db_session: AsyncSession,
) -> None:
    await seed_per_client_false_positives(async_db_session)
    pir = await AsyncPIRRepo(async_db_session).create(
        {"title": "Watch nginx", "criteria": {"industries": ["nginx"]}}, client_id="default"
    )

    result = await crossref_service.get_pir_crossrefs(async_db_session, pir.id)

    assert sorted(c["cve_id"] for c in result["matched_cves"]) == TRUE_POSITIVES


async def test_crossref_actor_matches_only_rows_not_marked_by_their_own_client(
    async_db_session: AsyncSession,
) -> None:
    await seed_per_client_false_positives(async_db_session)
    row_ids = (await async_db_session.execute(select(CveTracker.id))).scalars().all()
    async_db_session.add_all(
        CveThreatActor(cve_tracker_id=i, threat_actor="Apt41") for i in row_ids
    )
    await async_db_session.flush()

    result = await crossref_service.get_ta_crossrefs(async_db_session, "Apt41")

    assert sorted(c["cve_id"] for c in result["matched_cves"]) == TRUE_POSITIVES
