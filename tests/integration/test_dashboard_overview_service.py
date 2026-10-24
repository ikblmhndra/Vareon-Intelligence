"""Service overview dashboard: scope client (KEV/FP), PIR + periode -- Postgres REAL."""

from __future__ import annotations

import datetime

import pytest
from cti_api.services.dashboard_overview import (
    get_attention,
    get_cve_exposure,
    get_map,
    get_ransomware,
)
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_TODAY = datetime.date.today()


async def test_attention_excludes_false_positive_and_applies_pir_period(
    async_db_session: AsyncSession,
) -> None:
    await AsyncClientRepo(async_db_session).ensure_default()
    async_db_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-0001", client_id="default", tech="Nginx", cisa_kev=True),
            CveTracker(cve_id="CVE-2026-0002", client_id="default", tech="Nginx", cisa_kev=True),
        ]
    )
    await async_db_session.flush()
    await AsyncCveFalsePositiveRepo(async_db_session).mark("CVE-2026-0002", "default")

    repo = AsyncArticleRepo(async_db_session)
    old = _TODAY - datetime.timedelta(days=40)
    await repo.upsert(
        url="https://example.com/old",
        title="Old Qilin",
        source="S",
        posted_on=old,
        confirmed_incident=True,
    )
    pir_repo = AsyncPIRRepo(async_db_session)
    await pir_repo.create(
        {"title": "Qilin", "criteria": {"threat_actors": ["Qilin"]}, "start_date": old},
        client_id="default",
    )

    out = await get_attention(async_db_session, client_id="default", days=7)
    assert out["kev_in_stack"] == 1
    assert out["kev_without_ticket"] == 1
    # Artikel hanya ada di luar periode 7 hari: PIR tidak boleh dihitung.
    assert out["pir_hits"] == 0
    assert out["brief"]["headline"] == "1 CVE KEV cocok dengan tech stack klien."


async def test_map_ransomware_and_cve_exposure_shapes(async_db_session: AsyncSession) -> None:
    await AsyncClientRepo(async_db_session).ensure_default()
    async_db_session.add(
        CveTracker(cve_id="CVE-2026-0009", client_id="default", tech="Nginx", cisa_kev=True)
    )
    await async_db_session.flush()

    m = await get_map(async_db_session, client_id="default", days=7)
    assert m["points"] == [] and m["client_countries"] == []
    r = await get_ransomware(async_db_session, days=None)
    assert len(r["weekly"]) == 8 and r["total"] == 0
    e = await get_cve_exposure(async_db_session, client_id="default", days=7)
    assert [i["cve_id"] for i in e["items"]] == ["CVE-2026-0009"]
    assert e["items"][0]["ticket_id"] is None and e["open_kev"] == 1
