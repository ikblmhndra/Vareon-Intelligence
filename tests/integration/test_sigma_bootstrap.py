"""Bootstrap API memuat snapshot Sigma bawaan paket hanya saat `sigma_rules` kosong (spec 4.2)."""

from __future__ import annotations

import pytest
import structlog.testing
from cti_core.db.models import SigmaRule
from cti_core.db.models.auth import Client
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


async def test_sigma_failure_does_not_break_bootstrap(
    api_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cti_api.main as main

    def boom(session) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("sigma rusak")

    monkeypatch.setattr(main, "ensure_sigma_rules", boom)
    await api_session.execute(delete(Client).where(Client.client_id == "default"))
    with structlog.testing.capture_logs() as logs:
        await main.bootstrap_reference_rows(api_session)  # tidak boleh raise
    assert await api_session.get(Client, "default") is not None
    assert any(e["event"] == "sigma_bootstrap_failed" for e in logs)
