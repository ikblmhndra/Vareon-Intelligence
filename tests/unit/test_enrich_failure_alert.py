"""Alert Telegram "enrichment gagal" (`cti_worker.tasks.enrich._alert_enrichment_failure`): satu
pesan per jendela cooldown walau ratusan task gagal bersamaan, teks di-escape, dan kegagalan
Telegram/Redis tidak pernah melempar ke pemanggil (best-effort)."""

from __future__ import annotations

from typing import Any

import pytest


class FakeRedis:
    """`set(nx=True)` seperti Redis asli: hanya kunci pertama yang menang."""

    def __init__(self) -> None:
        self.keys: dict[str, tuple[str, int | None]] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and key in self.keys:
            return None
        self.keys[key] = (value, ex)
        return True


@pytest.fixture
def alert(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test-secret")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test-session")
    monkeypatch.setenv("WORKER__ENRICH_FAILURE_ALERT_COOLDOWN_MIN", "15")
    from cti_core.config import get_settings

    get_settings.cache_clear()
    from cti_worker.tasks import enrich

    yield enrich
    get_settings.cache_clear()


def _wire(monkeypatch: pytest.MonkeyPatch, fake: FakeRedis, sent: list[tuple[str, str]]) -> None:
    import redis
    from cti_alerts import telegram

    monkeypatch.setattr(redis.Redis, "from_url", lambda *_a, **_k: fake)
    monkeypatch.setattr(
        telegram, "send_alert", lambda topic, text, **_k: sent.append((topic, text))
    )


def test_one_alert_per_cooldown_window_even_when_many_tasks_fail(
    alert: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, sent = FakeRedis(), []
    _wire(monkeypatch, fake, sent)

    for _ in range(5):
        alert._alert_enrichment_failure("BadRequestError", "Unsupported model <mimo-auto>", 5)

    assert len(sent) == 1
    topic, text = sent[0]
    assert topic == "scraper_health"
    assert "BadRequestError" in text and "Menunggu replay: 5 artikel" in text
    assert "&lt;mimo-auto&gt;" in text and "<mimo-auto>" not in text  # HTML di-escape
    assert fake.keys["cti:enrich:failed_alerted"][1] == 15 * 60  # jendela dari setelan


def test_a_failing_telegram_never_raises(alert: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import redis
    from cti_alerts import telegram

    def down(*_a: object, **_k: object) -> None:
        raise ConnectionError("telegram unreachable")

    monkeypatch.setattr(redis.Redis, "from_url", lambda *_a, **_k: FakeRedis())
    monkeypatch.setattr(telegram, "send_alert", down)

    alert._alert_enrichment_failure("TypeError", "x", 1)  # tidak melempar
