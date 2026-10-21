"""Digest kesehatan scraper (`cti_worker.tasks.scrape._digest_due`): daftar masalah yang SAMA tidak
dikirim ulang dalam jendela repeat (sebelumnya pesan identik tiap 30 menit selama masalahnya ada),
daftar yang BERUBAH langsung terkirim, dan Redis mati tidak boleh membungkam alert (fail-open)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


class FakeRedis:
    def __init__(self) -> None:
        self.keys: dict[str, int | None] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and key in self.keys:
            return None
        self.keys[key] = ex
        return True


class BrokenRedis:
    def set(self, *_a: object, **_k: object) -> None:
        raise ConnectionError("redis down")


@pytest.fixture
def scrape(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test-secret")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test-session")
    from cti_worker.tasks import scrape as module

    return module


def problem(scraper_id: str, status: str) -> Any:
    return SimpleNamespace(scraper_id=scraper_id, status=status)


def test_the_same_problem_list_is_sent_once_per_window(scrape: Any) -> None:
    fake = FakeRedis()
    problems = [problem("a", "degraded"), problem("b", "dead")]

    assert scrape._digest_due(problems, 3600, fake) is True
    assert scrape._digest_due(list(reversed(problems)), 3600, fake) is False  # urutan tak penting
    assert list(fake.keys.values()) == [3600]  # jendela = repeat_s


def test_a_changed_problem_list_is_sent_at_once(scrape: Any) -> None:
    fake = FakeRedis()
    first = [problem("a", "degraded")]

    assert scrape._digest_due(first, 3600, fake) is True
    assert scrape._digest_due([*first, problem("b", "dead")], 3600, fake) is True  # scraper baru
    assert scrape._digest_due([problem("a", "dead")], 3600, fake) is True  # status berubah


def test_a_broken_redis_still_sends(scrape: Any) -> None:
    assert scrape._digest_due([problem("a", "degraded")], 3600, BrokenRedis()) is True
