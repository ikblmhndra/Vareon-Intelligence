"""`cti_core.db.engine.get_sync_engine` -- batas waktu koneksi (ROADMAP #23).

`runtime_secrets.overlay` memanggil sesi sync ini dari dalam event loop API. Host DB yang tidak
menjawab (SYN hilang) menahan `connect()` sampai timeout TCP OS (~2 menit) dan membekukan SELURUH
proses API, bukan cuma satu request; `connect_timeout` memotongnya jadi beberapa detik, dan overlay
fail-open ke `.env`. `create_engine` di-monkeypatch: tes ini tidak membuka koneksi apa pun.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from cti_core.config import get_settings
from cti_core.db.engine import get_sync_engine

SYNC_URL = "postgresql+psycopg://x:x@127.0.0.1:1/x"


@pytest.fixture
def engine_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", SYNC_URL)
    monkeypatch.setenv("AUTH__JWT_SECRET", "test-secret")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test-session")
    get_settings.cache_clear()
    get_sync_engine.cache_clear()
    yield monkeypatch
    get_sync_engine.cache_clear()  # jangan sampai engine palsu tertinggal di cache
    get_settings.cache_clear()


def test_the_sync_engine_is_created_with_a_five_second_connect_timeout(
    engine_env: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_engine(url: str, **kwargs: Any) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    engine_env.setattr("cti_core.db.engine.create_engine", fake_create_engine)

    get_sync_engine()

    assert captured["url"] == SYNC_URL
    assert captured["kwargs"]["connect_args"] == {"connect_timeout": 5}
