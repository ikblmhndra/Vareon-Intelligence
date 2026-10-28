"""`ensure_defaults` mengisi `content_kind` di semua baris yang namanya cocok -- Postgres REAL
(testcontainers). P6 spec 3.2."""

from __future__ import annotations

import pytest
from cti_core.db.repositories.source_reliability import AsyncSourceReliabilityRepo
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_ensure_defaults_sets_content_kind_on_existing_rows(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncSourceReliabilityRepo(async_db_session)
    await repo.add_entry(
        source_name="Mandiant",
        analyst_name="analyst1",
        reliability_grade="A",
        credibility_code="1",
        notes="",
    )

    inserted = await repo.ensure_defaults({"mandiant": "vendor_research", "Hackernews": "news"})

    # Hanya baris BARU yang dikembalikan (mendorong recompute), baris lama cuma dapat kind.
    assert inserted == ["Hackernews"]
    mandiant = await repo.get_by_name_ci("Mandiant")
    assert mandiant is not None
    assert mandiant.content_kind == "vendor_research"
    assert (mandiant.reliability_grade, mandiant.origin) == ("A", "analyst")
    hn = await repo.get_by_name_ci("Hackernews")
    assert hn is not None
    assert hn.content_kind == "news"

    assert await repo.ensure_defaults({"Hackernews": "advisory"}) == []
    await async_db_session.refresh(hn)
    assert hn.content_kind == "advisory"
