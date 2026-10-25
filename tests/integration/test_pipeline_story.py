"""P3 end-to-end di Postgres REAL: `run_pipeline` -> resolve story (sesi sendiri) -> persist
menempelkan artikel ke story. Yang diganti cuma LLM (classify, TTP), fetch, dan alert; stage
NLP berat (summarize/score) dan ekstraksi IOC juga diganti seperti
`test_enrich_cross_source_dedup.py`.

Sesi pipeline di sini `sync_session()` sungguhan (commit), karena `resolve_story` meng-commit
story di koneksinya sendiri; tiap test membersihkan baris yang ia buat."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from cti_core.db.engine import sync_session
from cti_core.db.models.article import Article
from cti_core.db.models.story import Story
from cti_core.urlkit import url_hash
from cti_enrich import pipeline
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.score import ScoreResult
from sqlalchemy import delete, select

LEAD_URL = "https://example.com/p3-lead"
FOLLOW_URL = "https://example.org/p3-follow"
REPLAY_URL = "https://example.com/p3-replay"
REPLAY_TITLE = "Zyxelion router botnet hijacks thousands of devices"


@pytest.fixture
def rec(_migrated_schema: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    r: dict[str, Any] = {"classify": 0, "ttp": 0, "alerts": 0, "fail": False}

    def fake_classify(title: str) -> ClassifyResult:
        r["classify"] += 1
        if r["fail"]:
            raise RuntimeError("LLM 503")
        return ClassifyResult(
            related_cyber=True,
            confidence=0.9,
            reason="vuln",
            industries_impacted=["Finance"],
            audit={"model": "fake"},
        )

    def fake_ttp(sent: str) -> pipeline.TtpResult:
        r["ttp"] += 1
        return pipeline.TtpResult(has_techniques=False)

    def fake_alerts(result: object) -> None:
        r["alerts"] += 1

    monkeypatch.setattr(pipeline, "classify", fake_classify)
    monkeypatch.setattr(pipeline, "extract_ttps", fake_ttp)
    monkeypatch.setattr(pipeline, "route_alerts", fake_alerts)
    monkeypatch.setattr(
        pipeline,
        "fetch_text",
        lambda url: (
            "Attackers chain CVE-2026-91001 and CVE-2026-91002 in Acme VPN. " * 20
            if url in (LEAD_URL, FOLLOW_URL)
            else "Botnet text. " * 20
        ),
    )
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())
    try:
        yield r
    finally:
        with sync_session() as s:
            hashes = [url_hash(u) for u in (LEAD_URL, FOLLOW_URL, REPLAY_URL)]
            story_ids = s.scalars(select(Article.story_id).where(Article.url_hash.in_(hashes)))
            ids = {i for i in story_ids if i is not None}
            s.execute(delete(Article).where(Article.url_hash.in_(hashes)))
            s.execute(
                delete(Story).where(
                    Story.id.in_(ids) | Story.title.in_([REPLAY_TITLE, _LEAD_TITLE])
                )
            )


_LEAD_TITLE = "Acme VPN zero-day chain under active exploitation"


def _run(url: str, title: str, source: str) -> pipeline.PipelineOutcome:
    with sync_session() as s:
        return pipeline.run_pipeline(
            title=title, url=url, posted_on=None, source=source, scraper_id=None, session=s
        )


def test_follow_up_sharing_cves_inherits(rec: dict[str, Any]) -> None:
    lead = _run(LEAD_URL, _LEAD_TITLE, "Vendor Blog")
    follow = _run(FOLLOW_URL, "Patch now: Acme fixes two VPN bugs", "Aggregator")

    assert lead.story_id is not None and follow.story_id == lead.story_id
    assert rec["classify"] == 1 and rec["ttp"] == 1  # LLM hanya untuk lead
    assert rec["alerts"] == 2  # alert tetap per artikel
    with sync_session() as s:
        story = s.get(Story, lead.story_id)
        assert story is not None
        assert story.article_count == 2 and story.source_count == 2
        assert story.lead_article_id == lead.article_id
        assert sorted(story.cve_ids) == ["CVE-2026-91001", "CVE-2026-91002"]
        assert story.classify is not None
        assert story.classify["industries_impacted"] == ["Finance"]
        assert "audit" not in story.classify
        rows = {
            a.url_hash: a
            for a in s.scalars(
                select(Article).where(
                    Article.url_hash.in_([url_hash(LEAD_URL), url_hash(FOLLOW_URL)])
                )
            )
        }
        lead_row = rows[url_hash(LEAD_URL)]
        follow_row = rows[url_hash(FOLLOW_URL)]
        assert lead_row.story_match == "lead"
        assert follow_row.story_id == lead.story_id and follow_row.story_match == "cve"
        audit = follow_row.raw_enrichment["classify"]
        assert audit["inherited_from_story"] == lead.story_id
        assert audit["lead_article_id"] == lead.article_id


def test_replay_reuses_empty_story(rec: dict[str, Any]) -> None:
    rec["fail"] = True
    with pytest.raises(RuntimeError):
        _run(REPLAY_URL, REPLAY_TITLE, "Vendor Blog")
    with sync_session() as s:  # story sudah dibuat resolver, artikelnya belum ada
        empty = s.scalars(select(Story).where(Story.title == REPLAY_TITLE)).all()
        assert len(empty) == 1 and empty[0].article_count == 0

    rec["fail"] = False
    outcome = _run(REPLAY_URL, REPLAY_TITLE, "Vendor Blog")
    assert outcome.accepted and outcome.story_id == empty[0].id
    with sync_session() as s:
        stories = s.scalars(select(Story).where(Story.title == REPLAY_TITLE)).all()
        assert len(stories) == 1 and stories[0].article_count == 1
        article = s.scalar(select(Article).where(Article.url_hash == url_hash(REPLAY_URL)))
        assert article is not None and article.story_match == "lead"


def test_other_article_matching_empty_story_keeps_its_rule(rec: dict[str, Any]) -> None:
    """Story kosong milik percobaan gagal artikel lain: artikel BEDA (sumber lain) yang cocok
    ke sana tetap dicatat dengan aturan resolver aslinya, bukan `lead`."""
    rec["fail"] = True
    with pytest.raises(RuntimeError):
        _run(REPLAY_URL, REPLAY_TITLE, "Vendor Blog")
    rec["fail"] = False
    outcome = _run(FOLLOW_URL, REPLAY_TITLE, "Aggregator")
    assert outcome.accepted
    with sync_session() as s:
        article = s.scalar(select(Article).where(Article.url_hash == url_hash(FOLLOW_URL)))
        assert article is not None and article.story_match == "title_exact"
