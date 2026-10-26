"""`gate_stats` dan task `relevance.evaluate` di Postgres beneran (testcontainers).

Test task membuka `sync_session()` sendiri dan commit, jadi baris seed dibersihkan manual."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any, ClassVar

import pytest
from cti_core.db.engine import sync_session
from cti_core.db.models.article import Article, RejectedArticle
from cti_core.db.models.relevance import RelevanceModel
from cti_core.db.repositories.relevance import RelevanceModelRepo
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

NOW = dt.datetime.now(dt.UTC)
BP = "Security Technology & Best Practices"


def _rel(decision: str, in_band: bool = True) -> dict[str, Any]:
    return {"relevance": {"model_id": 1, "probs": {}, "in_band": in_band, "decision": decision}}


def _article(n: str, decision: str, *, in_band: bool = True, bp: bool = False,
             at: dt.datetime = NOW) -> Article:  # fmt: skip
    return Article(
        url=f"https://gs.example/{n}", url_hash=f"gs-{n}", title=n, source="T",
        first_seen_at=at, last_seen_at=at, seen_count=1, created_at=at,
        news_type=BP if bp else "Ransomware", raw_enrichment=_rel(decision, in_band),
    )  # fmt: skip


def _rejected(n: str, decision: str, at: dt.datetime = NOW) -> RejectedArticle:
    return RejectedArticle(
        url=f"https://gs.example/{n}", url_hash=f"gs-{n}", title=n, source="T",
        reason="not cyber", rejected_at=at, raw_enrichment=_rel(decision),
    )  # fmt: skip


def test_gate_stats_counts_band_and_audit(db_session: Session) -> None:
    db_session.execute(delete(Article))
    db_session.execute(delete(RejectedArticle))
    old = NOW - dt.timedelta(days=30)
    m = dt.timedelta(minutes=1)
    db_session.add_all(
        [
            _article("shadow-agree", "shadow"),
            _article("shadow-bp", "shadow", bp=True),
            _article("out-of-band", "llm", in_band=False),
            _article("gated", "gated"),
            _article("old-shadow", "shadow", at=old),
            _article("audit-agree-old", "audit", at=NOW - 3 * m),
            _article("audit-agree-new", "audit", at=NOW - 1 * m),
            _rejected("rej-shadow", "shadow"),
            _rejected("rej-audit", "audit", at=NOW - 2 * m),
        ]
    )
    db_session.flush()
    repo = RelevanceModelRepo(db_session)

    stats = repo.gate_stats(since=NOW - dt.timedelta(days=14), revert_samples=2)

    # dalam jendela: shadow-agree, shadow-bp, audit x2, rej-shadow, rej-audit = 6; setuju = 3
    assert (stats.band_n, stats.band_agree) == (6, 3)
    # dua audit terbaru, terbaru dulu: audit-agree-new (T), rej-audit (F)
    assert stats.audit_last == [True, False]


@pytest.fixture
def clean(_migrated_schema: None) -> Iterator[None]:
    def wipe() -> None:
        with sync_session() as s:
            s.execute(delete(Article))
            s.execute(delete(RejectedArticle))
            s.execute(delete(RelevanceModel))

    wipe()
    yield
    wipe()


@pytest.fixture
def mod(_migrated_schema: None):
    from cti_worker.tasks import relevance

    return relevance


def _activate(artifact: bytes = b"x", gate_state: str = "shadow") -> int:
    with sync_session() as s:
        row = RelevanceModel(
            status="active", artifact=artifact, feature_version="v", n_examples=1,
            class_counts={}, metrics={}, gate_state=gate_state,
        )  # fmt: skip
        s.add(row)
        s.flush()
        return row.id


def _gate_state(model_id: int) -> str:
    with sync_session() as s:
        return s.execute(
            select(RelevanceModel.gate_state).where(RelevanceModel.id == model_id)
        ).scalar_one()


def _patch_healthy(monkeypatch, mod) -> list[tuple[str, str]]:
    from cti_enrich.relevance import model as model_mod
    from cti_enrich.stages import relevance as stage

    monkeypatch.setattr(model_mod, "loads", lambda data: object())
    monkeypatch.setattr(stage, "needs_retrain", lambda session: False)
    monkeypatch.setattr(mod.train, "delay", lambda: pytest.fail("train tidak boleh dipicu"))
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mod, "alert_ops", lambda text, *, key, cooldown_s=3600: sent.append((key, text))
    )
    return sent


def _seed_agreeing_band(n: int = 200) -> None:
    with sync_session() as s:
        s.add_all([_article(f"band{i}", "shadow") for i in range(n)])


def test_evaluate_alerts_and_retrains_on_corrupt_artifact(clean, mod, monkeypatch) -> None:
    _activate(b"x")
    alerts: list[str] = []
    trained: list[bool] = []
    monkeypatch.setattr(mod, "alert_ops", lambda text, *, key, cooldown_s=3600: alerts.append(key))
    monkeypatch.setattr(mod, "_trigger_train", lambda: trained.append(True) or True)

    out = mod.evaluate()

    assert alerts == ["relevance:load"]
    assert trained == [True]
    assert out["action"] == "retrain"


def test_evaluate_switches_to_gate_and_alerts(clean, mod, monkeypatch) -> None:
    model_id = _activate()
    sent = _patch_healthy(monkeypatch, mod)
    _seed_agreeing_band()

    out = mod.evaluate()

    assert out["action"] == "changed"
    assert _gate_state(model_id) == "gate"
    assert [k for k, _ in sent] == ["relevance:gate:gate"]
    assert "shadow -> gate" in sent[0][1]


def test_evaluate_unchanged_state_sends_no_alert(clean, mod, monkeypatch) -> None:
    model_id = _activate()
    sent = _patch_healthy(monkeypatch, mod)
    _seed_agreeing_band(5)

    out = mod.evaluate()

    assert out["action"] == "none"
    assert _gate_state(model_id) == "shadow"
    assert sent == []


@pytest.mark.parametrize("failing", ["redis", "telegram"])
def test_evaluate_commits_state_when_alert_fails(clean, mod, monkeypatch, failing) -> None:
    import cti_alerts.telegram as telegram
    import redis
    from cti_enrich.relevance import model as model_mod
    from cti_enrich.stages import relevance as stage

    model_id = _activate()
    monkeypatch.setattr(model_mod, "loads", lambda data: object())
    monkeypatch.setattr(stage, "needs_retrain", lambda session: False)

    class _Client:
        def set(self, *args: object, **kwargs: object) -> bool:
            if failing == "redis":
                raise redis.ConnectionError("unreachable")
            return True

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("telegram down")

    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, url: _Client()))
    monkeypatch.setattr(telegram, "send_alert", boom)
    _seed_agreeing_band()

    out = mod.evaluate()

    assert out["action"] == "changed"
    assert _gate_state(model_id) == "gate"


class _FakeRedis:
    store: ClassVar[dict[str, str]] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True


def _fake_redis(monkeypatch, *, broken: bool = False) -> None:
    import redis

    _FakeRedis.store = {}

    def from_url(cls, url):
        if broken:
            raise redis.ConnectionError("unreachable")
        return _FakeRedis()

    monkeypatch.setattr(redis.Redis, "from_url", classmethod(from_url))


def _set_mode(monkeypatch, mode: str) -> None:
    from cti_core.config import get_settings

    monkeypatch.setattr(get_settings().relevance, "mode", mode)


def _count_train(monkeypatch, mod) -> list[bool]:
    from cti_enrich.stages import relevance as stage

    calls: list[bool] = []
    monkeypatch.setattr(mod.train, "delay", lambda: calls.append(True))
    monkeypatch.setattr(stage, "needs_retrain", lambda session: True)
    return calls


def test_evaluate_triggers_train_once_per_day(clean, mod, monkeypatch) -> None:
    _fake_redis(monkeypatch)
    calls = _count_train(monkeypatch, mod)

    first = mod.evaluate()
    second = mod.evaluate()

    assert calls == [True]
    assert first["train_triggered"] is True
    assert second["train_triggered"] is False


def test_evaluate_never_trains_when_mode_off(clean, mod, monkeypatch) -> None:
    _fake_redis(monkeypatch)
    _set_mode(monkeypatch, "off")
    calls = _count_train(monkeypatch, mod)

    mod.evaluate()

    assert calls == []


def test_evaluate_skips_train_when_redis_fails(clean, mod, monkeypatch) -> None:
    _fake_redis(monkeypatch, broken=True)
    calls = _count_train(monkeypatch, mod)

    out = mod.evaluate()

    assert calls == []
    assert out["train_triggered"] is False


def test_evaluate_reverts_gate_when_mode_not_auto(clean, mod, monkeypatch) -> None:
    model_id = _activate(gate_state="gate")
    sent = _patch_healthy(monkeypatch, mod)
    _set_mode(monkeypatch, "shadow")

    out = mod.evaluate()

    assert out["action"] == "changed"
    assert _gate_state(model_id) == "shadow"
    assert [k for k, _ in sent] == ["relevance:gate:shadow"]


def test_evaluate_reverts_gate_on_low_audit_agreement(clean, mod, monkeypatch) -> None:
    model_id = _activate(gate_state="gate")
    sent = _patch_healthy(monkeypatch, mod)
    with sync_session() as s:
        # 50 sampel audit, 40 setuju (80% < 92%)
        s.add_all(
            [
                _article(f"aud{i}", "audit", bp=i >= 40, at=NOW - dt.timedelta(minutes=i))
                for i in range(50)
            ]
        )

    out = mod.evaluate()

    assert out["action"] == "changed"
    assert _gate_state(model_id) == "shadow"
    assert [k for k, _ in sent] == ["relevance:gate:shadow"]
