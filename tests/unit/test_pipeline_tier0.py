"""Sumber terstruktur (`default_relevance="always"`) melewati classify + TTP di `run_pipeline`;
`_relevance_for` di task `enrich.article` menerjemahkan `scraper_id` ke (kind, relevance)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from cti_core.config import RelevanceSettings, StorySettings
from cti_enrich import pipeline
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.persist import _audit_fields
from cti_enrich.stages.score import ScoreResult


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    rec: dict[str, Any] = {"classify": 0, "ttp": 0, "persist": []}

    def fake_classify(title: str) -> ClassifyResult:
        rec["classify"] += 1
        return ClassifyResult(related_cyber=True, confidence=0.9, reason="llm")

    def fake_ttp(sent: str) -> pipeline.TtpResult:
        rec["ttp"] += 1
        return pipeline.TtpResult(has_techniques=False)

    def fake_persist(**kw: Any) -> Any:
        rec["persist"].append(kw)
        return MagicMock(id=1, seen_count=1)

    # Jalur story (P3) diuji di `test_pipeline_story.py`; di sini perilaku Tier 0 0.8.6.
    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(
            story=StorySettings(enabled=False), relevance=RelevanceSettings(mode="off")
        ),
    )
    monkeypatch.setattr(pipeline, "_known_article", lambda session, url: None)
    monkeypatch.setattr(pipeline, "classify", fake_classify)
    monkeypatch.setattr(pipeline, "extract_ttps", fake_ttp)
    monkeypatch.setattr(pipeline, "persist", fake_persist)
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: "Isi artikel. " * 40)
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())
    monkeypatch.setattr(pipeline, "_track_cve_mentions", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "route_alerts", lambda result: None)
    return rec


def _run(**extra: Any) -> pipeline.PipelineOutcome:
    return pipeline.run_pipeline(
        title="CVE-2026-0001 added to KEV",
        url="https://example.com/kev",
        posted_on=None,
        source="CISA KEV",
        scraper_id="cisa_kev",
        session=MagicMock(),
        **extra,
    )


def test_always_skips_classify_and_ttp(calls: dict[str, Any]) -> None:
    outcome = _run(default_relevance="always", content_kind="kev")
    assert outcome.accepted
    assert calls["classify"] == 0
    assert calls["ttp"] == 0
    classify_result = calls["persist"][0]["classify_result"]
    assert _audit_fields(classify_result)["raw_enrichment"]["classify"] == {
        "skipped": "default_relevance=always",
        "content_kind": "kev",
    }


def test_classify_default_unchanged(calls: dict[str, Any]) -> None:
    _run()
    assert calls["classify"] == 1
    assert calls["ttp"] == 1


@pytest.fixture
def enrich(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test-secret")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test-session")
    from cti_worker.tasks import enrich as module

    return module


def test_relevance_for_unknown_or_none(enrich: Any) -> None:
    assert enrich._relevance_for(None) == (None, "classify")
    assert enrich._relevance_for("no_such_scraper") == (None, "classify")
    assert enrich._relevance_for("cisa_kev") == ("kev", "always")
