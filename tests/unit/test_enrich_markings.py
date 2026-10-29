"""`_relevance_for` membawa marking TLP/PAP sumber (spec P7a 3.4)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from cti_scraper import registry


@pytest.fixture
def enrich(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test-secret")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test-session")
    from cti_worker.tasks import enrich as module

    return module


def test_none_is_clear(enrich: Any) -> None:
    assert enrich._relevance_for(None) == (None, "classify", "clear", "clear")


def test_registered_scraper_ends_clear(enrich: Any) -> None:
    registry.discover()
    assert enrich._relevance_for("cisa_kev")[2:] == ("clear", "clear")


def test_meta_marking_is_returned(enrich: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = SimpleNamespace(
        content_kind="news", default_relevance="classify", tlp="amber", pap="red"
    )
    monkeypatch.setattr(registry, "get", lambda _id: SimpleNamespace(meta=meta))
    assert enrich._relevance_for("x") == ("news", "classify", "amber", "red")
