"""Input `cve_id` di endpoint CVE lewat HTTP: dinormalisasi, divalidasi, dan daftar bulk dibuang
duplikatnya. Tanpa ini `cve-2026-7001` jadi baris FP/ticket tersendiri yang tak pernah ketemu oleh
query lain, id yang kepanjangan untuk `String(20)` berujung 500, dan `bulk-*` dengan id kembar
kena `IntegrityError`."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cti_api.services import cve_email as cve_email_service
from cti_api.services import cve_lookup as cve_lookup_service
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

CVE = "CVE-2026-7001"
OTHER = "CVE-2026-7002"


async def _seed(session: AsyncSession) -> None:
    await AsyncClientRepo(session).ensure_default()
    session.add_all(
        [
            CveTracker(cve_id=CVE, client_id="default", tech="nginx"),
            CveTracker(cve_id=OTHER, client_id="default", tech="nginx"),
        ]
    )
    await session.flush()


async def test_lowercase_id_in_the_path_acts_on_the_canonical_row(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed(api_session)
    h = auth_header()
    lower = CVE.lower()

    ack = await api_client.post(
        f"/api/cve/{lower}/acknowledge", headers=h, json={"analyst_name": "a"}
    )
    assert ack.status_code == 200
    for spelling in (CVE, lower):
        ticket = (await api_client.get(f"/api/cve/{spelling}/ticket", headers=h)).json()
        assert (ticket["cve_id"], ticket["acknowledged_by"]) == (CVE, "a")

    fp = AsyncCveFalsePositiveRepo(api_session)
    assert (await api_client.post(f"/api/cve/{lower}/false-positive", headers=h)).status_code == 200
    assert await fp.list_cve_ids("default") == [CVE]
    assert (
        await api_client.delete(f"/api/cve/{lower}/false-positive", headers=h)
    ).status_code == 200
    assert await fp.list_cve_ids("default") == []


@pytest.mark.parametrize("bad", ["not-a-cve", "CVE-2026-1", "CVE-2026-123456789012"])
async def test_malformed_id_is_rejected_before_anything_is_written(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    bad: str,
) -> None:
    await _seed(api_session)
    h = auth_header()
    calls = [
        ("post", f"/api/cve/{bad}/false-positive", {}),
        ("delete", f"/api/cve/{bad}/false-positive", {}),
        ("get", f"/api/cve/{bad}/ticket", {}),
        ("put", f"/api/cve/{bad}/ticket", {"json": {"comments": "x"}}),
        ("post", f"/api/cve/{bad}/acknowledge", {"json": {"analyst_name": "a"}}),
        ("post", f"/api/cve/{bad}/exploit-lookup", {}),
    ]

    with patch.object(
        cve_lookup_service, "_lookup_exploitdb", AsyncMock(return_value=[])
    ) as lookup:
        for method, url, kwargs in calls:
            resp = await getattr(api_client, method)(url, headers=h, **kwargs)
            assert resp.status_code == 422, (method, url)

    lookup.assert_not_called()  # tidak ada panggilan keluar ke exploit-db untuk id sampah
    assert (await api_client.get("/api/cve/tickets?include_fp=true", headers=h)).json()[
        "total"
    ] == 0
    assert await AsyncCveFalsePositiveRepo(api_session).list_cve_ids("default") == []


async def test_bulk_endpoints_normalize_dedupe_and_validate_the_whole_list(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed(api_session)
    h = auth_header()
    both_spellings = [CVE, CVE.lower()]

    ack = await api_client.post(
        "/api/cve/bulk-acknowledge",
        headers=h,
        json={"cve_ids": both_spellings, "analyst_name": "a"},
    )
    assert (ack.status_code, ack.json()["acknowledged"]) == (200, 1)
    fp = await api_client.post(
        "/api/cve/bulk-false-positive", headers=h, json={"cve_ids": both_spellings}
    )
    assert (fp.status_code, fp.json()["marked"]) == (200, 1)

    # satu id tidak valid menggagalkan seluruh permintaan: tidak ada yang tersentuh
    bad = [OTHER, "nope"]
    ack_bad = await api_client.post(
        "/api/cve/bulk-acknowledge", headers=h, json={"cve_ids": bad, "analyst_name": "a"}
    )
    fp_bad = await api_client.post("/api/cve/bulk-false-positive", headers=h, json={"cve_ids": bad})
    assert (ack_bad.status_code, fp_bad.status_code) == (422, 422)
    assert list((await api_client.get("/api/cve/ack-statuses", headers=h)).json()) == [CVE]
    assert await AsyncCveFalsePositiveRepo(api_session).list_cve_ids("default") == [CVE]


async def test_draft_email_accepts_lowercase_ids(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """LLM dan Graph di-mock di titik yang sama dengan `test_cve_router_snapshot.py`."""
    await _seed(api_session)
    fake_validation = {"summary": "s", "risk_context": "r", "primary_remediation_action": []}
    mocks = {
        "_llm_cve_validator": MagicMock(return_value=fake_validation),
        "_dedup_mitigation": MagicMock(return_value={"alternative_remediation_action": []}),
        "_dedup_risk_context": MagicMock(return_value=""),
        "create_graph_draft": MagicMock(return_value="graph-msg-1"),
    }

    with ExitStack() as stack:
        for name, mock in mocks.items():
            stack.enter_context(patch.object(cve_email_service, name, mock))
        resp = await api_client.post(
            "/api/cve/draft-email", headers=auth_header(), json={"cve_ids": [CVE.lower()]}
        )

    assert (resp.status_code, resp.json()["cve_count"]) == (200, 1)
