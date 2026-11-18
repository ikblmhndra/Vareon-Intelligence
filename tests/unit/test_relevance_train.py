"""Pemisahan holdout dan metrik band untuk latih model relevansi (P5, Task 6)."""

from __future__ import annotations

import datetime as dt
from typing import Any

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


def _assert_telegram_html_safe(text: str) -> None:
    """Parse mode HTML Telegram menolak `<`/`>` mentah di luar tag yang dikenal (insiden dev
    2026-10-26: "agreement 0.949 < 0.95" -> `Can't parse entities`)."""
    stripped = text.replace("<b>", "").replace("</b>", "")
    assert "<" not in stripped and ">" not in stripped, text


def test_train_rejected_alert_escapes_reason(monkeypatch) -> None:
    import contextlib

    import cti_core.db.engine as engine
    import cti_enrich.relevance.embedder as embedder_mod
    import cti_enrich.relevance.train as train_mod

    _env(monkeypatch)
    import cti_worker.tasks.relevance as tasks

    sent: list[str] = []
    keys: list[str] = []
    monkeypatch.setattr(
        tasks, "alert_ops", lambda text, *, key, **kw: (sent.append(text), keys.append(key))
    )
    monkeypatch.setattr(engine, "sync_session", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: None)
    monkeypatch.setattr(
        train_mod,
        "run_training",
        lambda *a, **kw: train_mod.TrainOutcome("rejected", 1, {}, "agreement 0.949 < 0.95"),
    )
    try:
        tasks.train()
    finally:
        from cti_core.config import get_settings

        get_settings.cache_clear()
    # Satu alert per kind; teks + key kind `article` tidak berubah, kind `tweet` menyebut dirinya.
    assert keys == ["cti:relevance:train_rejected", "cti:relevance:train_rejected:tweet"]
    for text in sent:
        _assert_telegram_html_safe(text)
        assert "0.949 &lt; 0.95" in text
    assert sent[0].startswith("<b>Model relevansi baru DITOLAK</b>")
    assert sent[1].startswith("<b>Model relevansi tweet baru DITOLAK</b>")


def test_gate_change_alert_is_html_safe(monkeypatch) -> None:
    _env(monkeypatch)
    import cti_worker.tasks.relevance as tasks

    sent: list[str] = []
    monkeypatch.setattr(tasks, "alert_ops", lambda text, **kw: sent.append(text))
    tasks._alert_gate_change("shadow", "gate", 200, 195, None)
    _assert_telegram_html_safe(sent[0])


# ── kind tweet (spec tweet-llm-cost, Part C) ─────────────────────────────────────────────

_TWEET_VOCAB = {
    "reject": ["giveaway", "webinar", "football", "coffee", "holiday", "concert", "podcast"],
    "threat_news": ["ransomware", "breach", "exploit", "leak", "botnet", "zeroday", "victim"],
}


def _tweets(label: str, n: int) -> list[Example]:
    words = _TWEET_VOCAB[label]
    return [
        Example(
            title=" ".join(words[(i + k) % len(words)] for k in (0, 2, 3)) + f" t{label[0]}{i}",
            label=label,
            at=NOW - dt.timedelta(days=30 + i % 20),
        )
        for i in range(n)
    ]


def _fake_training_db(monkeypatch, examples: list[Example]) -> dict[str, Any]:
    """`run_training` tanpa Postgres: repo palsu mencatat panggilan, dataset tweet palsu, dan
    dataset artikel yang tidak boleh disentuh untuk kind `tweet`."""
    import cti_enrich.relevance.train as train_mod

    calls: dict[str, Any] = {"lock": [], "activate": [], "rejected": []}

    class _Repo:
        def __init__(self, session: Any) -> None: ...

        def lock(self, kind: str = "article") -> None:
            calls["lock"].append(kind)

        def purge(self, older_than: dt.datetime) -> int:
            return 0

        def activate(self, **kw: Any) -> int:
            calls["activate"].append(kw)
            return 7

        def add_rejected(self, **kw: Any) -> int:
            calls["rejected"].append(kw)
            return 8

    class _Verdicts:
        def __init__(self, session: Any) -> None: ...

        def purge(self, older_than: dt.datetime) -> int:
            return 0

    def no_articles(session: Any) -> list[Example]:
        raise AssertionError("kind tweet tidak boleh membaca dataset artikel")

    monkeypatch.setattr(train_mod, "RelevanceModelRepo", _Repo)
    monkeypatch.setattr(train_mod, "TweetVerdictRepo", _Verdicts)
    monkeypatch.setattr(train_mod, "load_examples", no_articles)
    monkeypatch.setattr(train_mod, "load_tweet_examples", lambda session: examples)
    return calls


def test_training_tweet_kind_with_two_classes(monkeypatch) -> None:
    from cti_core.config import RelevanceSettings
    from cti_enrich.relevance.train import run_training

    from tests.unit.relevance_fakes import FakeEmbedder

    calls = _fake_training_db(monkeypatch, _tweets("reject", 600) + _tweets("threat_news", 600))

    out = run_training(None, FakeEmbedder(), RelevanceSettings(), NOW, kind="tweet")  # type: ignore[arg-type]

    assert out.status == "active", out.reason
    assert calls["lock"] == ["tweet"]
    assert len(calls["activate"]) == 1
    act = calls["activate"][0]
    assert act["kind"] == "tweet"
    assert act["class_counts"] == {"reject": 600, "threat_news": 600}
    assert set(out.metrics["confusion"]) == {"reject", "threat_news"}
    assert set(out.metrics["holdout_counts"]) == {"reject", "threat_news"}


def test_tweet_training_skips_below_minimum_per_class(monkeypatch) -> None:
    from cti_core.config import RelevanceSettings
    from cti_enrich.relevance.train import run_training

    from tests.unit.relevance_fakes import FakeEmbedder

    calls = _fake_training_db(monkeypatch, _tweets("reject", 50) + _tweets("threat_news", 1000))

    out = run_training(None, FakeEmbedder(), RelevanceSettings(), NOW, kind="tweet")  # type: ignore[arg-type]

    assert out.status == "skipped"
    assert out.reason is not None and "reject" in out.reason
    assert "threat_news" not in out.reason
    assert out.metrics["class_counts"] == {"reject": 50, "threat_news": 1000}
    assert calls["activate"] == [] and calls["rejected"] == []


def test_train_failure_of_one_kind_does_not_stop_the_other(monkeypatch) -> None:
    import contextlib

    import cti_core.db.engine as engine
    import cti_enrich.relevance.embedder as embedder_mod
    import cti_enrich.relevance.train as train_mod
    from structlog.testing import capture_logs

    _env(monkeypatch)
    import cti_worker.tasks.relevance as tasks

    def run_training(*a: Any, kind: str = "article", **kw: Any) -> Any:
        if kind == "article":
            raise RuntimeError("article boom")
        return train_mod.TrainOutcome("skipped", None, {}, "kurang data")

    monkeypatch.setattr(engine, "sync_session", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(embedder_mod, "get_embedder", lambda: None)
    monkeypatch.setattr(train_mod, "run_training", run_training)
    try:
        with capture_logs() as logs:
            out = tasks.train()
    finally:
        from cti_core.config import get_settings

        get_settings.cache_clear()
    assert set(out) == {"tweet"} and out["tweet"]["status"] == "skipped"
    [failed] = [e for e in logs if e["event"] == "relevance_train_failed"]
    assert failed["kind"] == "article" and failed["log_level"] == "error"


def test_evaluate_failure_of_one_kind_does_not_stop_the_other(monkeypatch) -> None:
    from structlog.testing import capture_logs

    _env(monkeypatch)
    import cti_worker.tasks.relevance as tasks

    def evaluate_kind(kind: str, cfg: Any, now: Any) -> dict[str, Any]:
        if kind == "article":
            raise RuntimeError("article boom")
        return {"action": "none", "state": "shadow"}

    monkeypatch.setattr(tasks, "_evaluate_kind", evaluate_kind)
    try:
        with capture_logs() as logs:
            out = tasks.evaluate()
    finally:
        from cti_core.config import get_settings

        get_settings.cache_clear()
    assert out == {"tweet": {"action": "none", "state": "shadow"}}
    [failed] = [e for e in logs if e["event"] == "relevance_evaluate_failed"]
    assert failed["kind"] == "article" and failed["log_level"] == "error"
