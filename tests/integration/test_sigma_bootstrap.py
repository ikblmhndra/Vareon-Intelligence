"""Bootstrap API memuat snapshot Sigma bawaan paket hanya saat `sigma_rules` kosong (spec 4.2)."""

from __future__ import annotations

from cti_core.db.models import SigmaRule
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def test_bootstrap_sigma_idempotent(api_session: AsyncSession) -> None:
    from cti_api.main import bootstrap_reference_rows  # lazy: butuh Settings valid

    await api_session.execute(delete(SigmaRule))
    await bootstrap_reference_rows(api_session)
    n1 = await api_session.scalar(select(func.count()).select_from(SigmaRule))
    await bootstrap_reference_rows(api_session)
    assert n1 is not None and n1 >= 1000
    assert await api_session.scalar(select(func.count()).select_from(SigmaRule)) == n1
