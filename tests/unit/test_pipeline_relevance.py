"""P5 Task 8: `run_pipeline` memakai stage relevansi (gate) sebelum LLM classify. Stage
di-monkeypatch (gaya `test_pipeline_tier1.py`), tanpa DB."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from cti_core.config import RelevanceSettings, StorySettings
from cti_enrich import pipeline
from cti_enrich.relevance.gate import GateDecision
from cti_enrich.relevance.model import Probs
from cti_enrich.stages import persist as persist_stage
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.relevance import RelevanceResult
from cti_enrich.stages.tier1 import Tier1Result
from cti_enrich.tier1.incident import IncidentVerdict


def _rel(decision: str = "gated", p: float = 0.93) -> RelevanceResult:
    return RelevanceResult(
        7,
        Probs(0.02, 0.05, p),
        GateDecision(decision, in_band=True),  # type: ignore[arg-type]
    )


@pytest.fixture
def rec(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    r: dict[str, Any] = {
        "classify": 0,
        "relevance": 0,
        "persist": [],
        "rejected": [],
        "rel": _rel(),
        "tier1": Tier1Result.empty(),
        "classify_result": ClassifyResult(related_cyber=True, confidence=0.9, reason="llm"),
    }

    def fake_classify(title: str) -> ClassifyResult:
        r["classify"] += 1
        return r["classify_result"]  # type: ignore[no-any-return]

    def fake_relevance(session: Any, **kw: Any) -> RelevanceResult | None:
        r["relevance"] += 1
        return r["rel"]  # type: ignore[no-any-return]

    def fake_persist(**kw: Any) -> Any:
        r["persist"].append(kw)
        return MagicMock(id=1, seen_count=1)

    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(story=StorySettings(enabled=False), relevance=RelevanceSettings()),
    )
    monkeypatch.setattr(pipeline, "_known_article", lambda session, url: None)
    monkeypatch.setattr(pipeline, "classify", fake_classify)
    monkeypatch.setattr(pipeline, "run_relevance", fake_relevance)
    monkeypatch.setattr(pipeline, "run_tier1", lambda **kw: r["tier1"])
    monkeypatch.setattr(
        pipeline, "extract_ttps", lambda sent: pipeline.TtpResult(has_techniques=False)
    )
    monkeypatch.setattr(pipeline, "normalize_ttp_result", lambda result, catalog: result)
    monkeypatch.setattr(pipeline, "load_catalog", lambda session: None)
    monkeypatch.setattr(pipeline, "persist", fake_persist)
    monkeypatch.setattr(pipeline, "persist_rejected", lambda **kw: r["rejected"].append(kw))
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: "body text")
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(
        pipeline.score_stage, "score", lambda *a, **k: pipeline.score_stage.ScoreResult()
    )
    monkeypatch.setattr(pipeline, "_track_cve_mentions", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "route_alerts", lambda result: None)
    return r


def _run(**extra: Any) -> pipeline.PipelineOutcome:
    return pipeline.run_pipeline(
        title="Acme Corp confirms data breach",
        url="https://example.com/a",
        posted_on=None,
        source="Example",
        scraper_id="example",
        session=MagicMock(),
        **extra,
    )


def test_gated_article_skips_classify(rec: dict[str, Any]) -> None:
    outcome = _run()

    assert rec["classify"] == 0
    assert outcome.accepted
    kw = rec["persist"][0]
    assert kw["classify_result"].audit["skipped"] == "relevance_gate"
    assert kw["relevance"].to_audit()["decision"] == "gated"


def test_gated_article_incident_from_rule(rec: dict[str, Any]) -> None:
    rec["tier1"] = Tier1Result(incident=IncidentVerdict(True, ("breached",), victim="Acme"))

    _run()

    cr = rec["persist"][0]["classify_result"]
    assert cr.confirmed_incident is True
    assert cr.victim_name == "Acme"


def test_gated_unconfirmed_incident_leaves_victim_empty(rec: dict[str, Any]) -> None:
    rec["tier1"] = Tier1Result(incident=IncidentVerdict(False, ("alleged",), victim="Acme"))

    _run()

    cr = rec["persist"][0]["classify_result"]
    assert cr.confirmed_incident is False
    assert cr.victim_name is None


def test_gated_lead_does_not_fill_story(rec: dict[str, Any]) -> None:
    _run()

    assert persist_stage._story_classify(rec["persist"][0]["classify_result"]) is None


def test_shadow_calls_classify_and_records(rec: dict[str, Any]) -> None:
    rec["rel"] = _rel("shadow")
    _run()
    assert rec["classify"] == 1
    assert rec["persist"][0]["relevance"].decision.decision == "shadow"

    rec["classify_result"] = ClassifyResult(related_cyber=False, reason="no")
    _run()
    assert rec["classify"] == 2
    assert rec["rejected"][0]["relevance"].decision.decision == "shadow"


def test_relevance_none_falls_back(rec: dict[str, Any]) -> None:
    rec["rel"] = None
    _run()
    assert rec["classify"] == 1
    assert rec["persist"][0]["relevance"] is None


def test_tier0_and_inherited_do_not_run_relevance(
    rec: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(default_relevance="always", content_kind="kev")
    assert rec["relevance"] == 0

    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(story=StorySettings(enabled=True), relevance=RelevanceSettings()),
    )
    link = SimpleNamespace(
        inherited={
            "related_cyber": True,
            "industries": [],
            "victim_countries": [],
            "actor_countries": [],
        },
        story_id=1,
        rule="cve",
        lead_article_id=2,
    )
    monkeypatch.setattr(pipeline, "resolve_story", lambda **kw: link)
    monkeypatch.setattr(
        pipeline,
        "classify_from_story",
        lambda *a, **k: ClassifyResult(related_cyber=True, audit={"inherited_from_story": 1}),
    )
    _run()
    assert rec["relevance"] == 0
    assert rec["classify"] == 0


def test_persist_writes_relevance_audit() -> None:
    cr = ClassifyResult(related_cyber=True, audit={"skipped": "relevance_gate"})
    out = persist_stage._with_relevance(persist_stage._audit_fields(cr), _rel(), cr)
    rel = out["raw_enrichment"]["relevance"]
    assert rel["decision"] == "gated" and rel["incident_source"] == "rule"
    assert out["raw_enrichment"]["classify"] == cr.audit
    plain = persist_stage._with_relevance({}, _rel("shadow"), ClassifyResult(related_cyber=True))
    assert "incident_source" not in plain["raw_enrichment"]["relevance"]
    assert persist_stage._with_relevance({}, None, cr) == {}


def test_persist_rejected_writes_relevance_after_llm_reject() -> None:
    """Shadow lalu LLM menolak: `rejected_articles.raw_enrichment["relevance"]` terisi."""
    captured: dict[str, Any] = {}

    class _Repo:
        def __init__(self, session: Any) -> None: ...

        def upsert(self, **kw: Any) -> None:
            captured.update(kw)

    cr = ClassifyResult(related_cyber=False, reason="no", audit={"raw": 1})
    with patch.object(persist_stage, "RejectedArticleRepo", _Repo):
        persist_stage.persist_rejected(
            session=MagicMock(), url="u", title="t", source="s", scraper_id=None,
            posted_on=None, classify_result=cr, relevance=_rel("shadow"),
        )  # fmt: skip

    rel = captured["raw_enrichment"]["relevance"]
    assert rel["decision"] == "shadow"
    assert captured["raw_enrichment"]["classify"] == {"raw": 1}
