"""Lifespan API: reconcile validitas indikator hanya diantre bila sidik jari TTL beda (P7a)."""

from __future__ import annotations

import pytest
from cti_core.config import get_settings
from cti_core.db.engine import async_session
from cti_core.db.models.report_state import JobState
from cti_core.indicator.validity import ttl_fingerprint
from sqlalchemy import delete

from tests.integration.test_lifespan_recompute import (
    _keep_logging_config as _keep_logging_config,
)
from tests.integration.test_lifespan_recompute import (
    _no_default_rows as _no_default_rows,
)
from tests.integration.test_lifespan_recompute import (
    _run_lifespan,
)

pytestmark = pytest.mark.asyncio
_KEY = "indicator.ttl_fingerprint"


async def _set_fingerprint(value: str | None) -> None:
    async with async_session() as s:
        await s.execute(delete(JobState).where(JobState.key == _KEY))
        if value is not None:
            s.add(JobState(key=_KEY, value=value))
        await s.commit()


async def test_enqueues_only_when_fingerprint_differs(
    _no_default_rows: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr("cti_api.main.send_recompute_all", lambda: None)
    monkeypatch.setattr("cti_api.main.send_reconcile_validity", lambda: calls.append(1))
    current = ttl_fingerprint(get_settings().indicator)
    try:
        await _set_fingerprint(None)
        await _run_lifespan()
        assert calls == [1]  # baris hilang

        await _set_fingerprint("stale")
        await _run_lifespan()
        assert calls == [1, 1]  # beda

        await _set_fingerprint(current)
        await _run_lifespan()
        assert calls == [1, 1]  # sama: tidak diantre
    finally:
        await _set_fingerprint(None)
