"""Task Celery `confidence.recompute_all` / `confidence.recompute_source`: recompute penuh di tabel
besar harus commit per batch (`commit_each_batch=True`) supaya lock baris tidak dipegang sepanjang
run. Logikanya dites di `tests/integration/test_confidence_service.py`."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from cti_core.config import get_settings

    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeSession:
    async def commit(self) -> None:
        return None


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    @contextlib.asynccontextmanager
    async def fake_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    async def fake_recompute(session: Any, **kwargs: Any) -> dict[str, int]:
        seen.append(kwargs)
        return {"updated": 0}

    monkeypatch.setattr("cti_core.db.engine.async_session", fake_session)
    monkeypatch.setattr("cti_api.services.confidence.recompute_all_confidence", fake_recompute)
    return seen


def test_recompute_all_commits_each_batch(calls: list[dict[str, Any]]) -> None:
    from cti_worker.tasks import confidence

    confidence.recompute_all.run()
    assert calls == [{"commit_each_batch": True}]


def test_recompute_source_commits_each_batch(calls: list[dict[str, Any]]) -> None:
    from cti_worker.tasks import confidence

    confidence.recompute_source.run("Src")
    assert calls == [{"source_name": "Src", "commit_each_batch": True}]
