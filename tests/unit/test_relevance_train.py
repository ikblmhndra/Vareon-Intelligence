"""Pemisahan holdout dan metrik band untuk latih model relevansi (P5, Task 6)."""

from __future__ import annotations

import datetime as dt

from cti_enrich.relevance.model import CLASSES, Example, Probs
from cti_enrich.relevance.train import band_metrics, confusion_matrix, split_holdout

NOW = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.UTC)


def _examples(n: int, days: int) -> list[Example]:
    """`n` contoh tersebar rata dalam `days` hari terakhir, kelas bergiliran."""
    return [
        Example(
            title=f"judul {i}",
            label=CLASSES[i % 3],
            at=NOW - dt.timedelta(days=days * i / n),
        )
        for i in range(n)
    ]


def test_split_holdout_time_and_fallback() -> None:
    # 300 contoh dalam 20 hari: 14 hari terakhir ~210 contoh (>= 150) -> holdout waktu.
    time_split = split_holdout(_examples(300, 20), now=NOW, holdout_days=14)
    assert time_split.kind == "time"
    assert len(time_split.train) + len(time_split.test) == 300
    assert all(e.at >= NOW - dt.timedelta(days=14) for e in time_split.test)
    assert all(e.at < NOW - dt.timedelta(days=14) for e in time_split.train)

    # 100 contoh: kurang dari 150 di jendela -> 20% berstrata.
    fallback = split_holdout(_examples(100, 30), now=NOW, holdout_days=14)
    assert fallback.kind == "stratified"
    assert len(fallback.test) == 20
    assert {e.label for e in fallback.test} == set(CLASSES)


def test_band_metrics_empty_band() -> None:
    probs = [Probs(0.5, 0.2, 0.3), Probs(0.1, 0.1, 0.8)]
    got = band_metrics(probs, ["reject", "threat_news"], 0.85)
    assert got["band_n"] == 0
    assert got["agreement"] == 0.0
    assert got["band_share"] == 0.0
    assert got["n"] == 2


def test_band_metrics_counts() -> None:
    probs = [
        Probs(0.05, 0.05, 0.90),  # dalam band, benar
        Probs(0.05, 0.05, 0.90),  # dalam band, benar
        Probs(0.05, 0.05, 0.90),  # dalam band, salah (label reject)
        Probs(0.05, 0.05, 0.90),  # dalam band, benar
        Probs(0.40, 0.20, 0.40),  # luar band
    ]
    labels = ["threat_news", "threat_news", "reject", "threat_news", "threat_news"]
    got = band_metrics(probs, labels, 0.85)
    assert got["band_n"] == 4
    assert got["band_share"] == 0.8
    assert got["agreement"] == 0.75
    assert got["n"] == 5


def test_confusion_matrix_counts() -> None:
    probs = [
        Probs(0.8, 0.1, 0.1),  # reject
        Probs(0.1, 0.1, 0.8),  # threat_news
        Probs(0.1, 0.1, 0.8),  # threat_news
        Probs(0.1, 0.7, 0.2),  # best_practice
    ]
    labels = ["reject", "threat_news", "reject", "threat_news"]
    got = confusion_matrix(probs, labels)
    assert got["reject"] == {"reject": 1, "best_practice": 0, "threat_news": 1}
    assert got["threat_news"] == {"reject": 0, "best_practice": 1, "threat_news": 1}
    assert got["best_practice"] == {"reject": 0, "best_practice": 0, "threat_news": 0}


def test_split_holdout_falls_back_when_a_class_is_missing_from_train() -> None:
    # Semua best_practice baru (3 hari terakhir): train waktu tidak punya kelas itu.
    old = [
        Example(f"o{i}", CLASSES[i % 2 * 2], NOW - dt.timedelta(days=20 + i % 5)) for i in range(60)
    ]
    new = [Example(f"n{i}", CLASSES[i % 3], NOW - dt.timedelta(days=i % 3)) for i in range(180)]
    got = split_holdout(old + new, now=NOW, holdout_days=14)
    assert got.kind == "stratified"
    assert {e.label for e in got.train} == set(CLASSES)


def _env(monkeypatch) -> None:
    from cti_core.config import get_settings

    monkeypatch.setenv("REDIS__URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test")
    get_settings.cache_clear()


def test_alert_ops_swallows_errors_and_logs(monkeypatch) -> None:
    """Redis tak terjangkau: tidak melempar, dan event `relevance_alert_failed` tercatat."""
    from cti_core.config import get_settings
    from structlog.testing import capture_logs

    _env(monkeypatch)
    from cti_worker.tasks.relevance import alert_ops

    try:
        with capture_logs() as logs:
            alert_ops("x", key="cti:test:alert")
    finally:
        get_settings.cache_clear()
    assert any(entry["event"] == "relevance_alert_failed" for entry in logs)


def test_alert_ops_dedupes_by_key(monkeypatch) -> None:
    import cti_alerts.telegram as telegram
    import redis
    from cti_core.config import get_settings

    _env(monkeypatch)
    from cti_worker.tasks.relevance import alert_ops

    seen: set[str] = set()

    class FakeRedis:
        def set(self, key: str, value: str, nx: bool, ex: int) -> bool:
            if key in seen:
                return False
            seen.add(key)
            return True

    sent: list[str] = []
    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(lambda url: FakeRedis()))
    monkeypatch.setattr(telegram, "send_alert", lambda kind, text: sent.append(text))
    try:
        alert_ops("a", key="k")
        alert_ops("b", key="k")
    finally:
        get_settings.cache_clear()
    assert sent == ["a"]
