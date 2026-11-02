"""P7g: `run_pipeline` = `prepare` (tanpa LLM) lalu `complete` bila relevansinya sudah diketahui,
selain itu job `classify`. `complete` membuat job `ttp` bila LLM TTP berlaku dan menulis
`llm_ttp_status`. Stage di-monkeypatch (gaya `test_pipeline_relevance.py`), tanpa DB."""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from cti_core.config import RelevanceSettings, StorySettings
from cti_core.db.models.enrich_job import EnrichJob
from cti_enrich import pipeline
from cti_enrich.relevance.gate import GateDecision
from cti_enrich.relevance.model import Probs
from cti_enrich.stages import classify as classify_stage
from cti_enrich.stages import extract_ttps as ttp_stage
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.relevance import RelevanceResult
from cti_enrich.stages.score import ScoreResult
from cti_enrich.story.attach import StoryLink

from tests.unit.enrich_job_fakes import FakeJobRepo, finish

BODY = "Isi artikel tentang serangan ransomware. " * 20
URL = "https://example.com/a"


def _rel(decision: str = "shadow", p: float = 0.71) -> RelevanceResult:
    return RelevanceResult(7, Probs(0.1, 0.19, p), GateDecision(decision, in_band=False))  # type: ignore[arg-type]


def _link(inherited: dict[str, Any] | None = None) -> StoryLink:
    return StoryLink(
        story_id=42,
        rule="cve" if inherited else "lead",
        inherited=inherited,
        lead_article_id=7 if inherited else None,
        cve_ids=frozenset({"CVE-2026-0002", "CVE-2026-0001"}),
    )


def _no_llm(*a: Any, **k: Any) -> Any:
    raise AssertionError("LLM tidak boleh dipanggil di enrich.article")


@pytest.fixture
def rec(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    r: dict[str, Any] = {
        "persist": [],
        "rejected": [],
        "alerts": [],
        "rel": _rel(),
        "link": _link(),
        "story": True,
        "fetched": BODY,
        "summary": "Ringkasan.",
        "jobs": FakeJobRepo(),
    }

    def fake_persist(**kw: Any) -> Any:
        r["persist"].append(kw)
        return MagicMock(id=11, seen_count=1)

    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(
            story=StorySettings(enabled=r["story"]), relevance=RelevanceSettings()
        ),
    )
    monkeypatch.setattr(classify_stage, "classify", _no_llm)
    monkeypatch.setattr(ttp_stage, "extract_ttps", _no_llm)
    monkeypatch.setattr(pipeline, "EnrichJobRepo", r["jobs"])
    monkeypatch.setattr(pipeline, "_known_article", lambda session, url: None)
    monkeypatch.setattr(pipeline, "run_relevance", lambda session, **kw: r["rel"])
    monkeypatch.setattr(pipeline, "resolve_story", lambda **kw: r["link"])
    monkeypatch.setattr(pipeline, "persist", fake_persist)
    monkeypatch.setattr(pipeline, "persist_rejected", lambda **kw: r["rejected"].append(kw))
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: r["fetched"])
    monkeypatch.setattr(pipeline, "summarize", lambda text: r["summary"])
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())
    monkeypatch.setattr(pipeline, "_track_cve_mentions", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "route_alerts", lambda result: r["alerts"].append(result))
    return r


def _run(title: str = "Acme Corp confirms data breach", **extra: Any) -> pipeline.PipelineOutcome:
    return pipeline.run_pipeline(
        title=title,
        url=URL,
        posted_on=datetime.date(2026, 11, 1),
        source="Example",
        scraper_id="example",
        session=MagicMock(),
        **extra,
    )


def test_uncertain_title_creates_classify_job_without_llm(rec: dict[str, Any]) -> None:
    outcome = _run(tlp="green")

    assert not outcome.accepted and not outcome.duplicate
    [job] = rec["jobs"].jobs
    assert outcome.pending_job_id == job.id
    assert job.kind == "classify" and job.input_text == BODY
    assert job.posted_on == datetime.date(2026, 11, 1)
    assert rec["persist"] == [] and rec["rejected"] == [] and rec["alerts"] == []
    prepared = pipeline.Prepared.from_job(job)
    assert prepared.story == rec["link"]
    assert prepared.relevance == rec["rel"]
    assert prepared.tlp == "green" and prepared.classify_result is None


def test_tier0_completes_with_ttp_skipped(rec: dict[str, Any]) -> None:
    outcome = _run(default_relevance="always", content_kind="kev")

    assert outcome.accepted and outcome.article_id == 11
    assert rec["persist"][0]["llm_ttp_status"] == "skipped"
    assert rec["jobs"].jobs == []
    assert len(rec["alerts"]) == 1


def test_gated_completes_and_creates_ttp_job(rec: dict[str, Any]) -> None:
    rec["rel"] = _rel("gated", 0.97)

    outcome = _run()

    assert outcome.accepted and outcome.pending_job_id is None
    assert rec["persist"][0]["llm_ttp_status"] == "pending"
    [job] = rec["jobs"].jobs
    assert job.kind == "ttp" and job.state == "pending"
    assert job.article_id == 11
    assert job.input_text == pipeline.ttp_job_input(BODY, "Ringkasan.")
    assert len(rec["alerts"]) == 1  # alert sekarang, TTP LLM menyusul (D1)


def test_inherited_completes_with_ttp_skipped(rec: dict[str, Any]) -> None:
    rec["link"] = _link({"related_cyber": True, "industries_impacted": ["Finance"]})

    outcome = _run()

    assert outcome.accepted and outcome.story_id == 42
    assert rec["persist"][0]["llm_ttp_status"] == "skipped"
    assert rec["jobs"].jobs == []


def test_best_practice_writes_skipped(rec: dict[str, Any]) -> None:
    _run()
    outcome = finish(
        rec["jobs"],
        ClassifyResult(related_cyber=True, security_tech_best_practice=True, reason="llm"),
    )

    assert outcome.news_type == "Security Technology & Best Practices"
    assert rec["persist"][0]["llm_ttp_status"] == "skipped"
    assert rec["jobs"].jobs == []


def test_empty_ttp_input_writes_skipped(rec: dict[str, Any]) -> None:
    rec["rel"] = _rel("gated", 0.97)
    rec["fetched"] = ""
    rec["summary"] = ""

    outcome = _run()

    assert outcome.accepted
    assert rec["persist"][0]["llm_ttp_status"] == "skipped"
    assert rec["jobs"].jobs == []


def test_duplicate_when_classify_job_pending(rec: dict[str, Any]) -> None:
    """Review Focus 1: URL sama dari feed lain (judul lain) selagi job classify-nya menunggu."""
    first = _run()
    second = _run(title="Acme breach: attackers stole customer records")

    assert first.pending_job_id is not None
    assert second.duplicate and not second.accepted and second.pending_job_id is None
    assert rec["jobs"].create_calls == 1
    assert len(rec["jobs"].jobs) == 1
    assert rec["persist"] == [] and rec["alerts"] == []


def test_prepared_context_round_trip() -> None:
    prepared = pipeline.Prepared(
        title="T",
        url=URL,
        posted_on=datetime.date(2026, 11, 2),
        source="S",
        scraper_id="s",
        text=BODY,
        story=_link({"related_cyber": True}),
        relevance=_rel("audit", 0.93),
        classify_result=None,
        content_kind="advisory",
        default_relevance="classify",
        tlp="amber",
        pap="green",
    )
    context = json.loads(json.dumps(prepared.to_context()))  # harus muat di JSONB
    job = EnrichJob(
        kind="classify",
        url=URL,
        title="T",
        source="S",
        scraper_id="s",
        posted_on=datetime.date(2026, 11, 2),
        input_text=BODY,
        context=context,
    )

    assert pipeline.Prepared.from_job(job) == prepared


def test_from_job_defaults_for_empty_context() -> None:
    """Baris migrasi / `on_failure` (`context={}`): bawaan sama dengan `run_pipeline`."""
    job = EnrichJob(
        kind="classify", url=URL, title="T", source="S", scraper_id=None, posted_on=None,
        input_text=None, context={},
    )  # fmt: skip

    prepared = pipeline.Prepared.from_job(job)

    assert prepared.text == "" and prepared.story is None and prepared.relevance is None
    assert (prepared.default_relevance, prepared.tlp, prepared.pap) == (
        "classify",
        "clear",
        "clear",
    )


def test_relevance_from_audit_inverts_to_audit() -> None:
    rel = _rel("gated", 0.97)
    assert RelevanceResult.from_audit({**rel.to_audit(), "incident_source": "rule"}) == rel
