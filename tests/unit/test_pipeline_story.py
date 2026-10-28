"""P3: `run_pipeline` dengan dedup story -- fetch sebelum classify, follow-up story yang sudah
punya classify mewarisinya (tanpa LLM classify/TTP), dan `STORY__ENABLED=false` = 0.8.6."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from cti_core.config import RelevanceSettings, StorySettings
from cti_core.db.repositories.story import StoryRepo
from cti_enrich import pipeline
from cti_enrich.stages import persist as persist_mod
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.score import ScoreResult
from cti_enrich.story.attach import StoryLink

INHERITED = {
    "related_cyber": True,
    "confidence": 0.8,
    "reason": "lead",
    "industries_impacted": ["Finance"],
    "security_tech_best_practice": False,
    "victim_countries": ["Indonesia"],
    "actor_countries": [],
    "confirmed_incident": True,
    "incident_confidence": 0.7,
    "incident_indicators": ["leak"],
    "victim_name": "Bank X",
}


def _link(rule: str = "cve", inherited: dict[str, Any] | None = None) -> StoryLink:
    return StoryLink(
        story_id=42,
        rule=rule,  # type: ignore[arg-type]
        inherited=inherited,
        lead_article_id=None if rule == "lead" else 7,
        cve_ids=frozenset({"CVE-2026-0001"}),
    )


@pytest.fixture
def rec(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    r: dict[str, Any] = {
        "classify": 0,
        "ttp": 0,
        "persist": [],
        "order": [],
        "resolve": [],
        "link": _link(),
        "enabled": True,
        "related": True,
        "fetched": "Isi artikel. " * 40,
        "discard": [],
        "rejected": [],
    }

    def fake_classify(title: str) -> ClassifyResult:
        r["classify"] += 1
        r["order"].append("classify")
        return ClassifyResult(related_cyber=r["related"], confidence=0.9, reason="llm")

    def fake_fetch(url: str) -> str:
        r["order"].append("fetch")
        return str(r["fetched"])

    def fake_ttp(sent: str) -> pipeline.TtpResult:
        r["ttp"] += 1
        return pipeline.TtpResult(has_techniques=False)

    def fake_persist(**kw: Any) -> Any:
        r["persist"].append(kw)
        return MagicMock(id=1, seen_count=1)

    def fake_resolve(**kw: Any) -> StoryLink:
        r["resolve"].append(kw)
        return r["link"]  # type: ignore[no-any-return]

    def fake_discard(self: Any, story_id: int) -> bool:
        r["discard"].append(story_id)
        return True

    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(
            story=StorySettings(enabled=r["enabled"]), relevance=RelevanceSettings(mode="off")
        ),
    )
    monkeypatch.setattr(pipeline, "_known_article", lambda session, url: None)
    monkeypatch.setattr(pipeline, "classify", fake_classify)
    monkeypatch.setattr(pipeline, "extract_ttps", fake_ttp)
    monkeypatch.setattr(pipeline, "persist", fake_persist)
    monkeypatch.setattr(pipeline, "persist_rejected", lambda **kw: r["rejected"].append(kw))
    monkeypatch.setattr(pipeline, "fetch_text", fake_fetch)
    monkeypatch.setattr(pipeline, "resolve_story", fake_resolve)
    # Dicegat di kelasnya: jalur mana pun yang memanggilnya (seharusnya tidak ada) tercatat.
    monkeypatch.setattr(StoryRepo, "discard_if_empty", fake_discard)
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())
    monkeypatch.setattr(pipeline, "_track_cve_mentions", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "route_alerts", lambda result: None)
    return r


def _run(title: str = "Bank X breach exposes CVE-2026-0001", **extra: Any) -> Any:
    return pipeline.run_pipeline(
        title=title,
        url="https://example.com/a",
        posted_on=None,
        source="Vendor",
        scraper_id="vendor",
        session=MagicMock(),
        **extra,
    )


def test_inherited_skips_llm(rec: dict[str, Any]) -> None:
    rec["link"] = _link("cve", INHERITED)
    outcome = _run()
    assert outcome.accepted and outcome.story_id == 42
    assert rec["classify"] == 0
    assert rec["ttp"] == 0
    kw = rec["persist"][0]
    assert kw["classify_result"].industries_impacted == ["Finance"]
    assert kw["classify_result"].victim_name == "Bank X"
    assert kw["classify_result"].audit == {
        "inherited_from_story": 42,
        "lead_article_id": 7,
        "match": "cve",
    }
    assert kw["story"] is rec["link"]


def test_inherited_best_practice_takes_best_practice_branch(rec: dict[str, Any]) -> None:
    rec["link"] = _link("title", {**INHERITED, "security_tech_best_practice": True})
    outcome = _run()
    assert outcome.news_type == "Security Technology & Best Practices"
    assert outcome.story_id == 42
    assert rec["classify"] == 0 and rec["ttp"] == 0
    assert rec["persist"][0]["story"] is rec["link"]


def test_known_story_without_classify_enriches_fully(rec: dict[str, Any]) -> None:
    rec["link"] = _link("cve", None)
    outcome = _run()
    assert rec["classify"] == 1
    assert rec["ttp"] == 1
    assert rec["persist"][0]["story"] is rec["link"]
    assert outcome.story_id == 42


def test_fetch_before_classify(rec: dict[str, Any]) -> None:
    rec["link"] = _link("lead")
    _run()
    assert rec["order"] == ["fetch", "classify"]
    assert rec["resolve"][0]["text"] == rec["fetched"]


def test_empty_fetch_uses_title_cves(rec: dict[str, Any]) -> None:
    rec["link"] = _link("lead")
    rec["fetched"] = ""
    outcome = _run(title="Patch for CVE-2026-0001")
    assert outcome.accepted
    call = rec["resolve"][0]
    assert call["text"] == ""
    assert call["title"] == "Patch for CVE-2026-0001"
    assert call["source"] == "Vendor"


def test_story_disabled_is_0_8_6(rec: dict[str, Any]) -> None:
    rec["enabled"] = False
    outcome = _run()
    assert rec["resolve"] == []
    assert rec["order"] == ["classify", "fetch"]
    assert rec["persist"][0]["story"] is None
    assert outcome.story_id is None


def test_story_disabled_rejected_never_fetches(rec: dict[str, Any]) -> None:
    rec["enabled"] = False
    rec["related"] = False
    _run()
    assert rec["order"] == ["classify"]
    assert rec["discard"] == []


def test_rejected_lead_keeps_story(rec: dict[str, Any]) -> None:
    """Ruling 11: story kosong tidak dihapus saat lead ditolak (artikel lain mungkin sudah
    resolve ke sana); hanya purge harian yang membuangnya."""
    rec["link"] = _link("lead")
    rec["related"] = False
    outcome = _run()
    assert not outcome.accepted
    assert rec["discard"] == []
    assert len(rec["rejected"]) == 1
    assert rec["persist"] == []


def test_rejected_follow_up_keeps_story(rec: dict[str, Any]) -> None:
    """Story yang dicocokkan milik artikel lain (mungkin masih di-enrich): jangan dihapus."""
    rec["link"] = _link("title_exact")
    rec["related"] = False
    _run()
    assert rec["discard"] == []


@pytest.fixture
def real_persist(monkeypatch: pytest.MonkeyPatch, rec: dict[str, Any]) -> list[dict[str, Any]]:
    """`persist` ASLI dengan repo tiruan: yang diuji argumen `StoryRepo.attach`."""
    attached: list[dict[str, Any]] = []
    upserts: list[dict[str, Any]] = []

    class FakeArticleRepo:
        def __init__(self, session: Any) -> None:
            pass

        def upsert(self, **kw: Any) -> Any:
            upserts.append(kw)
            return MagicMock(id=9, url_hash="h", seen_count=1)

        def set_enrichment(self, *a: Any, **k: Any) -> None:
            pass

    class FakeStoryRepo:
        def __init__(self, session: Any) -> None:
            pass

        def attach(self, story_id: int, **kw: Any) -> None:
            attached.append({"story_id": story_id, **kw})

    monkeypatch.setattr(persist_mod, "ArticleRepo", FakeArticleRepo)
    monkeypatch.setattr(persist_mod, "StoryRepo", FakeStoryRepo)
    monkeypatch.setattr(persist_mod, "IOCRepo", MagicMock())
    monkeypatch.setattr(persist_mod, "ArticleCveRepo", MagicMock())
    monkeypatch.setattr(persist_mod, "_get_allowlist", lambda session: [])
    monkeypatch.setattr(persist_mod, "apply_assessments", lambda session, ids: {})
    monkeypatch.setattr(pipeline, "persist", persist_mod.persist)
    rec["upserts"] = upserts
    return attached


def test_tier0_never_fills_story_classify(
    rec: dict[str, Any], real_persist: list[dict[str, Any]]
) -> None:
    rec["link"] = _link("lead")
    _run(default_relevance="always", content_kind="kev")
    assert rec["classify"] == 0
    assert len(real_persist) == 1
    assert real_persist[0]["story_id"] == 42
    assert real_persist[0]["article_id"] == 9
    assert real_persist[0]["classify"] is None
    assert real_persist[0]["cve_ids"] == {"CVE-2026-0001"}
    assert rec["upserts"][0]["story_id"] == 42
    assert rec["upserts"][0]["story_match"] == "lead"


def test_llm_classify_fills_story_classify(
    rec: dict[str, Any], real_persist: list[dict[str, Any]]
) -> None:
    rec["link"] = _link("lead")
    _run()
    classify = real_persist[0]["classify"]
    assert classify is not None
    assert classify["related_cyber"] is True and classify["reason"] == "llm"
    assert "audit" not in classify


def test_inherited_never_refills_story_classify(
    rec: dict[str, Any], real_persist: list[dict[str, Any]]
) -> None:
    rec["link"] = _link("cve", INHERITED)
    _run()
    assert real_persist[0]["classify"] is None
    assert rec["upserts"][0]["story_match"] == "cve"


def test_disabled_persist_writes_no_story_fields(
    rec: dict[str, Any], real_persist: list[dict[str, Any]]
) -> None:
    rec["enabled"] = False
    _run()
    assert real_persist == []
    assert "story_id" not in rec["upserts"][0]
