"""Integration test `cti_api.services.cve_lookup` + repo method baru
`AsyncCveTrackerRepo` (list_true_positive_cve_ids/list_by_cve_ids_any_
client/apply_epss_scores/apply_cisa_kev_hits/apply_exploit_hits) --
Postgres REAL (testcontainers). Fase 7.4 Grup B (survei 2026-09-19).

Panggilan HTTP eksternal (FIRST.org/CISA/exploit-db) di-mock
`unittest.mock.patch` di sini (sama pola kayak `tests/unit/test_mailer.py`
/`test_pkg_vuln_query.py`) -- verifikasi LIVE beneran dilakuin terpisah,
bukan bagian suite otomatis ini."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from cti_api.services import cve_lookup as cve_lookup_service
from cti_core.db.models.cve import CvePoc, CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo, AsyncCveTrackerRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _ensure_clients(session: AsyncSession) -> None:
    repo = AsyncClientRepo(session)
    await repo.ensure_default()
    await repo.create(client_id="acme", name="Acme", countries=[])


# ── AsyncCveTrackerRepo -- method baru ───────────────────────────────────────


async def test_list_true_positive_cve_ids_excludes_default_client_fp(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    async_db_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-1111", client_id="default", tech="nginx"),
            CveTracker(cve_id="CVE-2026-2222", client_id="default", tech="nginx"),
        ]
    )
    await async_db_session.flush()
    await AsyncCveFalsePositiveRepo(async_db_session).mark("CVE-2026-2222", "default")

    tp_ids = await AsyncCveTrackerRepo(async_db_session).list_true_positive_cve_ids()
    assert tp_ids == ["CVE-2026-1111"]


async def test_list_true_positive_cve_ids_judges_false_positive_per_client_row(
    async_db_session: AsyncSession,
) -> None:
    """FP itu per (cve_id, client_id). CVE masih true positive selama ada SATU client yang
    men-track-nya tanpa menandai FP -- bukan cuma FP milik client "default" yang dihitung."""
    await _ensure_clients(async_db_session)
    async_db_session.add_all(
        [
            # A: FP di default, tapi acme masih menganggapnya valid -> TP
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

    tp_ids = await AsyncCveTrackerRepo(async_db_session).list_true_positive_cve_ids()
    assert sorted(tp_ids) == ["CVE-2026-0101", "CVE-2026-0102"]


async def test_list_by_cve_ids_any_client_case_insensitive_multi_client(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    async_db_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-3333", client_id="default", tech="nginx"),
            CveTracker(cve_id="cve-2026-3333", client_id="acme", tech="apache"),
        ]
    )
    await async_db_session.flush()

    rows = await AsyncCveTrackerRepo(async_db_session).list_by_cve_ids_any_client(["cve-2026-3333"])
    assert {r.client_id for r in rows} == {"default", "acme"}


async def test_apply_epss_scores_updates_all_client_rows(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    async_db_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-4444", client_id="default", tech="nginx"),
            CveTracker(cve_id="CVE-2026-4444", client_id="acme", tech="apache"),
        ]
    )
    await async_db_session.flush()

    await AsyncCveTrackerRepo(async_db_session).apply_epss_scores(
        {"CVE-2026-4444": {"epss": 0.87, "percentile": 0.95, "date": "2026-09-19"}}
    )

    rows = await AsyncCveTrackerRepo(async_db_session).list_by_cve_ids_any_client(["CVE-2026-4444"])
    assert all(r.epss_score == 0.87 for r in rows)
    assert all(r.epss_percentile == 0.95 for r in rows)
    assert all(r.epss_checked_at is not None for r in rows)


async def test_apply_cisa_kev_hits_matches_and_sets_active_exploitation(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    async_db_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-5555", client_id="default", tech="nginx"),
            CveTracker(cve_id="CVE-2026-6666", client_id="default", tech="nginx"),
        ]
    )
    await async_db_session.flush()

    catalog = {
        "CVE-2026-5555": {
            "dateAdded": "2026-01-01",
            "vendorProject": "nginx",
            "vulnerabilityName": "Some RCE",
            "shortDescription": "desc",
            "requiredAction": "patch now",
        }
    }
    matched = await AsyncCveTrackerRepo(async_db_session).apply_cisa_kev_hits(
        catalog, ["CVE-2026-5555", "CVE-2026-6666"]
    )
    assert matched == ["CVE-2026-5555"]

    rows = await AsyncCveTrackerRepo(async_db_session).list_by_cve_ids_any_client(["CVE-2026-5555"])
    assert rows[0].cisa_kev is True
    assert rows[0].active_exploitation is True
    assert rows[0].cisa_kev_detail["vendor"] == "nginx"

    untouched = await AsyncCveTrackerRepo(async_db_session).list_by_cve_ids_any_client(
        ["CVE-2026-6666"]
    )
    assert untouched[0].cisa_kev is False


async def test_apply_exploit_hits_dedups_per_row_and_sets_poc_available(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    cve_default = CveTracker(cve_id="CVE-2026-7777", client_id="default", tech="nginx")
    cve_acme = CveTracker(cve_id="CVE-2026-7777", client_id="acme", tech="apache")
    async_db_session.add_all([cve_default, cve_acme])
    await async_db_session.flush()

    # baris "acme" udah punya satu POC exploit-db duluan -- harus KE-SKIP
    # dedup, bukan didobelin. Baris "default" belum punya apa-apa.
    # `refresh()` dulu -- append ke relationship yang belum di-load di sesi
    # async butuh state lama buat itung diff, lazy-load implisit gak jalan
    # sinkron di luar `await` (sama pola `AsyncArticleRepo.set_enrichment`).
    await async_db_session.refresh(cve_acme, attribute_names=["pocs"])
    cve_acme.pocs.append(
        CvePoc(url="https://www.exploit-db.com/exploits/1", source="exploit-db", poc_type="exploit")
    )
    await async_db_session.flush()

    exploits = [
        {
            "edb_id": "1",
            "title": "t1",
            "posted_on": "2026-01-01",
            "url": "https://www.exploit-db.com/exploits/1",
            "source": "exploit-db",
            "type": "exploit",
        },
        {
            "edb_id": "2",
            "title": "t2",
            "posted_on": "2026-01-02",
            "url": "https://www.exploit-db.com/exploits/2",
            "source": "exploit-db",
            "type": "exploit",
        },
    ]
    await AsyncCveTrackerRepo(async_db_session).apply_exploit_hits("CVE-2026-7777", exploits)

    rows = {
        r.client_id: r
        for r in await AsyncCveTrackerRepo(async_db_session).list_by_cve_ids_any_client(
            ["CVE-2026-7777"]
        )
    }
    assert len(rows["default"].pocs) == 2  # kedua exploit baru
    assert len(rows["acme"].pocs) == 2  # 1 lama + 1 baru, bukan 3 (dedup per-baris)
    assert rows["default"].poc_available is True
    assert rows["acme"].poc_available is True
    assert rows["default"].exploit_db_hits == exploits


# ── Service layer -- HTTP eksternal di-mock ─────────────────────────────────


async def test_run_epss_lookup_end_to_end(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    async_db_session.add(CveTracker(cve_id="CVE-2026-8888", client_id="default", tech="nginx"))
    await async_db_session.flush()

    fake_scores = {"CVE-2026-8888": {"epss": 0.5, "percentile": 0.8, "date": "2026-09-19"}}
    with patch.object(
        cve_lookup_service, "_fetch_epss_scores", AsyncMock(return_value=fake_scores)
    ):
        summary = await cve_lookup_service.run_epss_lookup(async_db_session)

    assert summary == {"checked": 1, "scored": 1, "no_data": 0}
    cve = (
        await AsyncCveTrackerRepo(async_db_session).list_by_cve_ids_any_client(["CVE-2026-8888"])
    )[0]
    assert cve.epss_score == 0.5


async def test_run_cisa_kev_lookup_end_to_end(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    async_db_session.add(CveTracker(cve_id="CVE-2026-9999", client_id="default", tech="nginx"))
    await async_db_session.flush()

    fake_catalog = {"CVE-2026-9999": {"vendorProject": "nginx", "dateAdded": "2026-01-01"}}
    with patch.object(cve_lookup_service, "_fetch_cisa_kev", AsyncMock(return_value=fake_catalog)):
        summary = await cve_lookup_service.run_cisa_kev_lookup(async_db_session)

    assert summary["matched"] == 1
    assert summary["matched_cves"] == ["CVE-2026-9999"]


async def test_run_exploit_db_single_lookup_success_and_error(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    async_db_session.add(CveTracker(cve_id="CVE-2026-1010", client_id="default", tech="nginx"))
    await async_db_session.flush()

    fake_exploits = [
        {
            "edb_id": "9",
            "title": "t",
            "posted_on": "2026-01-01",
            "url": "https://www.exploit-db.com/exploits/9",
            "source": "exploit-db",
            "type": "exploit",
        }
    ]
    with patch.object(
        cve_lookup_service, "_lookup_exploitdb", AsyncMock(return_value=fake_exploits)
    ):
        result = await cve_lookup_service.run_exploit_db_single_lookup(
            async_db_session, "CVE-2026-1010"
        )
    assert result == {"cve_id": "CVE-2026-1010", "found": 1, "error": None}

    with patch.object(
        cve_lookup_service, "_lookup_exploitdb", AsyncMock(side_effect=RuntimeError("boom"))
    ):
        result2 = await cve_lookup_service.run_exploit_db_single_lookup(
            async_db_session, "CVE-2026-1010"
        )
    assert result2["found"] == 0
    assert result2["error"] == "boom"


async def test_run_exploit_db_bulk_lookup_batches(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    for i in range(7):
        async_db_session.add(
            CveTracker(cve_id=f"CVE-2026-20{i:02d}", client_id="default", tech="nginx")
        )
    await async_db_session.flush()

    with (
        patch.object(cve_lookup_service, "_lookup_exploitdb", AsyncMock(return_value=[])),
        patch("asyncio.sleep", AsyncMock()),
    ):
        summary = await cve_lookup_service.run_exploit_db_bulk_lookup(async_db_session)

    assert summary["checked"] == 7
    assert summary["with_exploits"] == 0
    assert summary["errors"] == 0
