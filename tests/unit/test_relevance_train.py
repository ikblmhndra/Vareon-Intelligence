"""Pemisahan holdout dan metrik band untuk latih model relevansi (P5, Task 6)."""

from __future__ import annotations

import datetime as dt

from cti_enrich.relevance.model import CLASSES, Example, Probs
from cti_enrich.relevance.train import band_metrics, split_holdout

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


def test_alert_ops_swallows_errors(monkeypatch) -> None:
    """Redis tak terjangkau: `alert_ops` tidak boleh melempar."""
    from cti_core.config import get_settings
    from cti_worker.tasks.relevance import alert_ops

    monkeypatch.setenv("REDIS__URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test")
    get_settings.cache_clear()
    try:
        alert_ops("x", key="cti:test:alert")
    finally:
        get_settings.cache_clear()
