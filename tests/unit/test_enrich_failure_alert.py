"""Alert Telegram enrichment P7g (`cti_worker.tasks.llm_dispatch`): "gateway LLM mati" dan "job
gagal". Satu pesan per jenis per jendela cooldown walau dipanggil berkali-kali (worker paralel,
kegagalan massal), kunci Redis terpisah per jenis, teks di-escape, dan kegagalan Telegram/Redis
tidak pernah melempar ke pemanggil (best-effort)."""

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
def mod(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test-secret")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test-session")
    monkeypatch.setenv("WORKER__ENRICH_FAILURE_ALERT_COOLDOWN_MIN", "15")
    from cti_core.config import get_settings

    get_settings.cache_clear()
    from cti_worker.tasks import llm_dispatch

    yield llm_dispatch
    get_settings.cache_clear()


def _wire(monkeypatch: pytest.MonkeyPatch, fake: FakeRedis, sent: list[tuple[str, str]]) -> None:
    import redis
    from cti_alerts import telegram

    monkeypatch.setattr(redis.Redis, "from_url", lambda *_a, **_k: fake)
    monkeypatch.setattr(
        telegram, "send_alert", lambda topic, text, **_k: sent.append((topic, text))
    )


def test_llm_down_alerts_once_per_cooldown_window(
    mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, sent = FakeRedis(), []
    _wire(monkeypatch, fake, sent)

    for waiting in (30, 31, 32):
        mod.alert_llm_down(waiting)

    [(topic, text)] = sent
    assert topic == "scraper_health"
    assert "30 artikel" in text
    [(_key, (_, ttl))] = fake.keys.items()
    assert ttl == 15 * 60  # jendela dari setelan


def test_job_failed_alerts_once_and_escapes_html(mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    fake, sent = FakeRedis(), []
    _wire(monkeypatch, fake, sent)

    for _ in range(5):
        mod.alert_job_failed("Ransomware <b>hits</b>", "BadRequestError: Unsupported <mimo-auto>")

    [(topic, text)] = sent
    assert topic == "scraper_health"
    assert "&lt;mimo-auto&gt;" in text and "<mimo-auto>" not in text
    assert "&lt;b&gt;hits&lt;/b&gt;" in text


def test_each_alert_type_has_its_own_dedupe_key(mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    fake, sent = FakeRedis(), []
    _wire(monkeypatch, fake, sent)

    mod.alert_llm_down(3)
    mod.alert_job_failed("judul", "RuntimeError: x")

    assert len(sent) == 2 and len(fake.keys) == 2


@pytest.mark.parametrize(
    "call", [lambda m: m.alert_llm_down(1), lambda m: m.alert_job_failed("t", "e")]
)
def test_a_failing_telegram_never_raises(
    mod: Any, monkeypatch: pytest.MonkeyPatch, call: Any
) -> None:
    import redis
    from cti_alerts import telegram

    def down(*_a: object, **_k: object) -> None:
        raise ConnectionError("telegram unreachable")

    monkeypatch.setattr(redis.Redis, "from_url", lambda *_a, **_k: FakeRedis())
    monkeypatch.setattr(telegram, "send_alert", down)

    call(mod)  # tidak melempar


def test_enrich_llm_task_wires_the_failed_job_alert(
    mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run_job` tidak boleh mengimpor `cti_alerts`; task worker menyuntikkan alert-nya (R2)."""
    from cti_enrich import jobs
    from cti_worker.tasks import enrich

    seen: dict[str, Any] = {}

    def fake_run_job(job_id: int, **kw: Any) -> str:
        seen.update(kw)
        return "failed"

    monkeypatch.setattr(jobs, "run_job", fake_run_job)

    assert enrich.enrich_llm.run(job_id=7) == "failed"
    assert seen["on_failed"] is mod.alert_job_failed
