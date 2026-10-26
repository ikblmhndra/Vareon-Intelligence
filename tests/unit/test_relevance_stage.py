"""Stage relevansi (P5, Task 7): cache model, fallback ke LLM, dan impor tanpa sklearn."""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
import textwrap
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from cti_core.config import RelevanceSettings
from cti_enrich.relevance import embedder as embedder_mod
from cti_enrich.relevance import model as model_mod
from cti_enrich.relevance.embedder import set_embedder
from cti_enrich.relevance.model import Example, dumps, fit
from cti_enrich.stages import relevance as stage

from tests.unit.relevance_fakes import FakeEmbedder

NOW = dt.datetime(2026, 10, 25, tzinfo=dt.UTC)


def _trained() -> bytes:
    labels = ("reject", "best_practice", "threat_news")
    words = ("alpha beta", "gamma delta", "ransomware breach attack")
    ex = [Example(f"{words[i % 3]} item {i}", labels[i % 3], NOW) for i in range(60)]
    return dumps(fit(ex, FakeEmbedder()))


@pytest.fixture(autouse=True)
def _env() -> Any:
    set_embedder(FakeEmbedder())
    stage._reset_cache()
    yield
    set_embedder(None)
    stage._reset_cache()


def _row(artifact: bytes | None, fv: str | None = None, model_id: int = 1, gate: str = "shadow"):
    return SimpleNamespace(
        id=model_id,
        artifact=artifact,
        feature_version=fv or model_mod.feature_version(FakeEmbedder()),
        gate_state=gate,
    )


def _patch_active(monkeypatch: pytest.MonkeyPatch, rows: list[Any]) -> list[int]:
    calls: list[int] = []

    class _Repo:
        def __init__(self, session: Any) -> None: ...

        def get_active(self) -> Any:
            calls.append(1)
            return rows[0]

    monkeypatch.setattr(stage, "RelevanceModelRepo", _Repo)
    return calls


def _run(cfg: RelevanceSettings | None = None) -> Any:
    return stage.run_relevance(
        MagicMock(),  # sesi tiruan: `begin_nested()` (savepoint R4) dipakai di `_active`
        title="ransomware breach attack item 1",
        url="https://example.com/a",
        cfg=cfg or RelevanceSettings(),
    )


def test_off_returns_none_without_db(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_active(monkeypatch, [_row(_trained())])
    assert _run(RelevanceSettings(mode="off")) is None
    assert calls == []


def test_no_active_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_active(monkeypatch, [None])
    assert _run() is None


def test_feature_version_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_active(monkeypatch, [_row(_trained(), fv="other")])
    assert _run() is None


def test_predict_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_active(monkeypatch, [_row(_trained())])

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("x")

    monkeypatch.setattr(model_mod, "predict", boom)
    assert _run() is None


def test_garbage_artifact_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_active(monkeypatch, [_row(b"garbage")])
    assert _run() is None


def test_embedder_unavailable_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_active(monkeypatch, [_row(_trained())])

    def nope() -> Any:
        raise embedder_mod.EmbedderUnavailable("tidak ada")

    monkeypatch.setattr(stage, "get_embedder", nope)
    assert _run() is None


def test_result_and_audit_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_active(monkeypatch, [_row(_trained(), model_id=7)])
    res = _run()
    assert res is not None and res.model_id == 7
    assert res.decision.decision == "shadow"
    audit = res.to_audit()
    assert set(audit) == {"model_id", "probs", "in_band", "decision"}
    assert set(audit["probs"]) == {"reject", "best_practice", "threat_news"}
    assert isinstance(audit["in_band"], bool) and audit["decision"] == "shadow"


def test_cache_ttl_and_reload_only_on_model_change(monkeypatch: pytest.MonkeyPatch) -> None:
    art = _trained()
    rows = [_row(art, model_id=1, gate="shadow")]
    calls = _patch_active(monkeypatch, rows)
    loads_n: list[int] = []
    real_loads = model_mod.loads
    monkeypatch.setattr(model_mod, "loads", lambda b: (loads_n.append(1), real_loads(b))[1])
    now = [1000.0]
    monkeypatch.setattr(stage.time, "monotonic", lambda: now[0])

    assert _run() is not None
    assert _run() is not None
    assert len(calls) == 1 and len(loads_n) == 1  # cache dipakai

    now[0] += 601
    rows[0] = _row(art, model_id=1, gate="gate")  # gate_state berubah, model sama
    res = _run(RelevanceSettings(mode="auto"))
    assert len(calls) == 2 and len(loads_n) == 1  # tidak reload artifact
    assert res is not None and res.decision.decision in {"gated", "audit", "llm"}

    now[0] += 601
    rows[0] = _row(art, model_id=2)
    _run()
    assert len(loads_n) == 2  # model_id berubah -> reload


def test_needs_retrain(monkeypatch: pytest.MonkeyPatch) -> None:
    rows: list[Any] = [None]
    _patch_active(monkeypatch, rows)
    assert stage.needs_retrain(None) is True  # type: ignore[arg-type]
    rows[0] = _row(b"x", fv="other")
    assert stage.needs_retrain(None) is True  # type: ignore[arg-type]
    rows[0] = _row(b"x")
    assert stage.needs_retrain(None) is False  # type: ignore[arg-type]

    def nope() -> Any:
        raise embedder_mod.EmbedderUnavailable("tidak ada")

    monkeypatch.setattr(stage, "get_embedder", nope)
    rows[0] = None
    assert stage.needs_retrain(None) is False  # type: ignore[arg-type]


def test_stage_imports_without_sklearn() -> None:
    code = textwrap.dedent(
        """
        import sys
        for name in ("sklearn", "scipy", "joblib", "fastembed", "torch", "spacy"):
            sys.modules[name] = None
        import cti_enrich.stages.relevance as r
        import cti_enrich.relevance.gate as g
        assert "cti_enrich.relevance.model" not in sys.modules
        print("ok")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=180, check=False
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
