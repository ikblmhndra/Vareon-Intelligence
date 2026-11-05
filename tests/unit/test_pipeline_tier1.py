"""P4 Task 7: `run_pipeline` menjalankan Tier 1 dan meneruskan hasil gabungannya ke `route`
dan `persist`. Stage di-monkeypatch (gaya `test_pipeline_tier0.py`), tanpa DB. Sejak P7g vonis
LLM classify datang dari job (`_run` menyelesaikannya) dan LLM TTP = job `ttp`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import structlog
from cti_core.attack_ttp import TechniqueCatalog
from cti_core.config import RelevanceSettings, StorySettings
from cti_enrich import pipeline
from cti_enrich.stages import tier1 as tier1_stage
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.score import ScoreResult
from cti_enrich.stages.tier1 import Tier1Result
from cti_enrich.tier1.dictionary import build_dictionary

from tests.unit.enrich_job_fakes import FakeJobRepo, finish

BODY = (
    "The attackers dropped a web shell on the server. "
    "Researchers linked the intrusion to Lazarus Group, which also deployed Cobalt Strike. "
    "Initial access came from a phishing email sent to staff. "
) * 3


@pytest.fixture
def rec(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    r: dict[str, Any] = {
        "persist": [],
        "route": [],
        "classify_result": ClassifyResult(related_cyber=True, confidence=0.9, reason="llm"),
        "jobs": FakeJobRepo(),
    }

    def fake_persist(**kw: Any) -> Any:
        r["persist"].append(kw)
        return MagicMock(id=1, seen_count=1)

    real_route = pipeline.routing.route

    def spy_route(inp: Any) -> Any:
        r["route"].append(inp)
        return real_route(inp)

    dictionary = build_dictionary(
        groups=[("Lazarus Group", ["Hidden Cobra"])],
        software=[("Cobalt Strike", "tool", [])],
        ta_names=[],
        suppressed=[],
    )
    monkeypatch.setattr(tier1_stage, "get_dictionary", lambda session: dictionary)
    monkeypatch.setattr(tier1_stage, "_get_catalog", lambda session: TechniqueCatalog())
    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(
            story=StorySettings(enabled=False), relevance=RelevanceSettings(mode="off")
        ),
    )
    monkeypatch.setattr(pipeline, "_known_article", lambda session, url: None)
    monkeypatch.setattr(pipeline, "EnrichJobRepo", r["jobs"])
    monkeypatch.setattr(pipeline, "persist", fake_persist)
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: BODY)
    # Ringkasan sengaja tanpa aktor: aktor harus datang dari teks penuh lewat Tier 1.
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan pendek.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())
    monkeypatch.setattr(pipeline.routing, "route", spy_route)
    monkeypatch.setattr(pipeline, "_track_cve_mentions", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "route_alerts", lambda result: None)
    return r


def _run(
    rec: dict[str, Any], title: str = "Hackers breach a logistics firm", **extra: Any
) -> pipeline.PipelineOutcome:
    outcome = pipeline.run_pipeline(
        title=title,
        url="https://example.com/a",
        posted_on=None,
        source="Example",
        scraper_id="example",
        session=MagicMock(),
        **extra,
    )
    if outcome.pending_job_id is None:
        return outcome
    return finish(rec["jobs"], rec["classify_result"])  # vonis LLM job `classify`


def _ttp_jobs(rec: dict[str, Any]) -> list[Any]:
    return list(rec["jobs"].of_kind("ttp"))


def test_tier1_runs_on_always_path(rec: dict[str, Any]) -> None:
    _run(rec, default_relevance="always", content_kind="kev")

    assert _ttp_jobs(rec) == []
    kw = rec["persist"][0]
    assert isinstance(kw["tier1"], Tier1Result)
    merged = {t.ttp_id: t.source for t in kw["merged_ttps"]}
    assert merged["T1505.003"] == "keyword"


def test_keyword_not_sent_to_llm(rec: dict[str, Any]) -> None:
    _run(rec)

    # Job `ttp` membawa teks artikel saja; teknik keyword Tier 1 tidak ikut dikirim.
    assert [j.input_text for j in _ttp_jobs(rec)] == [
        pipeline.ttp_job_input(BODY, "Ringkasan pendek.")
    ]


def test_actor_from_full_text_reaches_routing(rec: dict[str, Any]) -> None:
    outcome = _run(rec)

    assert rec["route"][0].mentioned_group == ["lazarus group"]
    assert outcome.news_type != "Global Article"
    assert rec["persist"][0]["routing_result"].threat_actors == ["Lazarus group"]


def test_tier1_failure_keeps_article(rec: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier 1 gagal = hasil kosong: artikel tetap tersimpan, TTP LLM tetap dijadwalkan (job `ttp`;
    penggabungannya dengan sumber `llm` diuji di job runner, Task 4)."""

    def failing_tier1(**kw: Any) -> Tier1Result:
        structlog.get_logger().warning("tier1_failed", error="kaboom")
        return Tier1Result.empty()

    monkeypatch.setattr(pipeline, "run_tier1", failing_tier1)

    outcome = _run(rec)

    assert outcome.accepted
    kw = rec["persist"][0]
    assert kw["merged_ttps"] == []
    assert kw["llm_ttp_status"] == "pending" and len(_ttp_jobs(rec)) == 1
    assert kw["industries"] == ([], "llm")


def test_best_practice_gets_entities_and_industry_only(rec: dict[str, Any]) -> None:
    rec["classify_result"] = ClassifyResult(
        related_cyber=True,
        confidence=0.9,
        reason="llm",
        industries_impacted=["General"],
        security_tech_best_practice=True,
    )
    outcome = _run(rec, title="How banks should harden remote access")

    assert outcome.news_type == "Security Technology & Best Practices"
    assert _ttp_jobs(rec) == []
    kw = rec["persist"][0]
    tier1 = kw["tier1"]
    assert tier1.techniques == []  # teknik tidak dicari di cabang best practice
    assert tier1.malware == [("Cobalt Strike", "tool")]
    assert kw.get("merged_ttps") is None
    assert kw["ttp_result"] is None
    # LLM cuma "General" -> industri keyword Tier 1 menggantikannya.
    assert kw["industries"] == (["Finance & Insurance"], "keyword")
    # Ruling 11: aktor Tier 1 tidak disimpan di cabang best practice (routing tanpa aktor).
    assert tier1.actors == ["Lazarus Group"]
    assert kw["routing_result"].threat_actors == []


def test_mixed_general_list_keeps_ot_marker(rec: dict[str, Any]) -> None:
    """LLM ["General", "Energy & Utilities"] -> `resolve_industries` = ["General"] -> sumber
    keyword. Routing tetap menerima daftar mentah LLM + industri keyword (Ruling 12)."""
    rec["classify_result"] = ClassifyResult(
        related_cyber=True,
        confidence=0.9,
        reason="llm",
        industries_impacted=["General", "Energy & Utilities"],
    )

    outcome = _run(rec, title="Hackers breach banks across the region")

    kw = rec["persist"][0]
    assert kw["industries"] == (["Finance & Insurance"], "keyword")
    assert rec["route"][0].industries_impacted == [
        "General",
        "Energy & Utilities",
        "Finance & Insurance",
    ]
    assert "OT-relevant" in kw["routing_result"].msg_data
    assert outcome.accepted
