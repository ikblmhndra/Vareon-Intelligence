"""`run_pipeline` + Tier 1 terhadap Postgres REAL (P4 Task 7): sumber TTP, malware, industri
keyword, dan audit `raw_enrichment["tier1"]` tersimpan; `persist`/`routing` ASLI, LLM di-stub."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cti_core.db.models.article import Article
from cti_core.db.models.attack import AttackSoftware, AttackTechnique
from cti_core.urlkit import url_hash
from cti_enrich import pipeline
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.extract_ttps import Technique
from cti_enrich.stages.score import ScoreResult
from sqlalchemy import select
from sqlalchemy.orm import Session

URL = "https://example.com/tier1-pipeline"

BODY = (
    "A regional credit union disclosed an intrusion this week; the central bank was notified. "
    "The intruders exploited a public-facing VPN appliance to get in. "
    "They then ran PowerShell scripts (T1059.001) and dropped a web shell for persistence. "
    "Responders also found Cobalt Strike beacons on two hosts."
)


@pytest.fixture
def session(_migrated_schema: None) -> Iterator[Session]:
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def _stages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pipeline,
        "classify",
        lambda title: ClassifyResult(
            related_cyber=True,
            confidence=0.9,
            reason="intrusion",
            industries_impacted=["General"],
            audit={"model": "stub"},
        ),
    )
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: BODY)
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())
    monkeypatch.setattr(
        pipeline,
        "extract_ttps",
        lambda sent: pipeline.TtpResult(
            has_techniques=True,
            techniques=[
                Technique(
                    "T1190",
                    "Exploit Public-Facing Application",
                    evidence="exploited a public-facing VPN appliance",
                )
            ],
        ),
    )
    monkeypatch.setattr(pipeline, "route_alerts", lambda result: None)


def _seed(session: Session) -> None:
    session.add_all(
        [
            AttackTechnique(
                stix_id=f"attack-pattern--{tid}",
                attack_id=tid,
                name=name,
                tactics=[],
                domains=["enterprise-attack"],
                is_subtechnique="." in tid,
                parent_id=tid.split(".")[0] if "." in tid else None,
            )
            for tid, name in [
                ("T1190", "Exploit Public-Facing Application"),
                ("T1059", "Command and Scripting Interpreter"),
                ("T1059.001", "PowerShell"),
                ("T1505", "Server Software Component"),
                ("T1505.003", "Web Shell"),
            ]
        ]
    )
    session.add(
        AttackSoftware(
            stix_id="tool--cobalt-strike",
            software_id="S0154",
            name="Cobalt Strike",
            software_type="tool",
            aliases=[],
            domains=["enterprise-attack"],
        )
    )
    session.flush()


def test_pipeline_writes_sources(session: Session) -> None:
    _seed(session)

    outcome = pipeline.run_pipeline(
        title="Intrusion disclosed after VPN compromise",
        url=URL,
        posted_on=None,
        source="Test",
        scraper_id="t",
        session=session,
    )

    assert outcome.accepted and outcome.article_id is not None
    article = session.scalar(select(Article).where(Article.url_hash == url_hash(URL)))
    assert article is not None
    ttps = {t.ttp_id: t for t in article.ttps}
    assert {tid: t.source for tid, t in ttps.items()} == {
        "T1059.001": "explicit",
        "T1505.003": "keyword",
        "T1190": "llm",
    }
    assert ttps["T1190"].evidence == "exploited a public-facing VPN appliance"
    assert "T1059.001" in (ttps["T1059.001"].evidence or "")
    assert [(m.name, m.kind) for m in article.malware] == [("Cobalt Strike", "tool")]
    assert [(i.industry, i.source) for i in article.industries] == [
        ("Finance & Insurance", "keyword")
    ]
    assert set(article.raw_enrichment) >= {"classify", "tier1"}
    assert article.raw_enrichment["classify"] == {"model": "stub"}
    assert any(h["canonical"] == "Cobalt Strike" for h in article.raw_enrichment["tier1"]["hits"])
    # Sumber tanpa rating: dasar 50; bonus TTP hanya explicit + llm (2 x 5), keyword tidak.
    assert article.confidence_score == 60
