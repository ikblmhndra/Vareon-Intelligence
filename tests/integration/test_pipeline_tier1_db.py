"""`run_pipeline` + Tier 1 terhadap Postgres REAL (P4 Task 7): sumber TTP, malware, industri
keyword, dan audit `raw_enrichment["tier1"]` tersimpan; `persist`/`routing` ASLI, LLM di-stub.
P7g: vonis classify lewat job (`enrich_job_support`); TTP LLM = job `ttp` yang digabung job
runner (Task 4), jadi artikel awalnya hanya berisi teknik Tier 1."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cti_core.db.models.article import Article
from cti_core.db.models.attack import AttackSoftware, AttackTechnique
from cti_core.urlkit import url_hash
from cti_enrich import pipeline
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.extract_ttps import Technique, TtpResult
from cti_enrich.stages.score import ScoreResult
from cti_enrich.stages.summarize import make_dek
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.integration.enrich_job_support import job_for, run_with_verdict, share_session
from tests.integration.entity_support import seed_entity

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


VERDICT = ClassifyResult(
    related_cyber=True,
    confidence=0.9,
    reason="intrusion",
    industries_impacted=["General"],
    audit={"model": "stub"},
)
LLM_TTPS = TtpResult(
    has_techniques=True,
    techniques=[
        Technique(
            "T1190",
            "Exploit Public-Facing Application",
            evidence="exploited a public-facing VPN appliance",
        )
    ],
)


@pytest.fixture(autouse=True)
def _stages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: BODY)
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())
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
    # P7c: kamus Tier 1 dibangun dari entity_aliases (sync ATT&CK mengisinya, Task 9)
    seed_entity(session, "tool", "Cobalt Strike", external_id="S0154")
    session.flush()


def _run(session: Session) -> pipeline.PipelineOutcome:
    return run_with_verdict(
        session,
        VERDICT,
        title="Intrusion disclosed after VPN compromise",
        url=URL,
        posted_on=None,
        source="Test",
        scraper_id="t",
    )


def test_pipeline_writes_sources(session: Session) -> None:
    _seed(session)

    outcome = _run(session)

    assert outcome.accepted and outcome.article_id is not None
    article = session.scalar(select(Article).where(Article.url_hash == url_hash(URL)))
    assert article is not None
    ttps = {m.entity.external_id: m for m in article.mentions_of("attack-pattern")}
    assert {tid: t.method for tid, t in ttps.items()} == {
        "T1059.001": "explicit",
        "T1505.003": "keyword",
        "T1190": "keyword",  # job `ttp` menaikkannya ke `llm` (explicit > llm > keyword)
    }
    assert "T1059.001" in (ttps["T1059.001"].evidence or "")
    assert [(m.entity.name, m.entity.type) for m in article.mentions_of("malware", "tool")] == [
        ("Cobalt Strike", "tool")
    ]
    assert [(m.matched_alias, m.method) for m in article.mentions_of("identity")] == [
        ("Finance & Insurance", "keyword")
    ]
    assert set(article.raw_enrichment) >= {"classify", "tier1"}
    assert article.raw_enrichment["classify"] == {"model": "stub"}
    assert any(h["canonical"] == "Cobalt Strike" for h in article.raw_enrichment["tier1"]["hits"])
    # Sumber tanpa rating: F6 = 50. Poin TTP prioritas hanya explicit + llm, keyword tidak (P4);
    # TTP LLM baru datang lewat job `ttp`, jadi sekarang hanya explicit (1 x 3).
    assert article.confidence_score == 50
    assert article.score_reasons is not None
    assert {"code": "ttps", "points": 3} in article.score_reasons["priority"]
    assert article.llm_ttp_status == "pending"
    job = job_for(session, URL, "ttp")
    assert job is not None and job.article_id == article.id and job.input_text == BODY


def test_ttp_job_adds_llm_technique(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sesudah job `ttp` jalan: T1190 bersumber `llm` (bukti ada di teks), poin prioritas TTP
    explicit + llm (2 x 3), status `done`. `run_job` memakai sesi test (`share_session`)."""
    from cti_enrich import jobs

    share_session(monkeypatch, session)
    _seed(session)
    _run(session)
    job = job_for(session, URL, "ttp")
    assert job is not None
    monkeypatch.setattr(jobs, "extract_ttps", lambda sent: LLM_TTPS)

    assert jobs.run_job(job.id) == "done"

    article = session.scalar(select(Article).where(Article.url_hash == url_hash(URL)))
    assert article is not None
    session.refresh(article)
    ttps = {m.entity.external_id: m for m in article.mentions_of("attack-pattern")}
    assert {tid: t.method for tid, t in ttps.items()} == {
        "T1059.001": "explicit",
        "T1505.003": "keyword",
        "T1190": "llm",
    }
    assert ttps["T1190"].evidence == "exploited a public-facing VPN appliance"
    assert article.score_reasons is not None
    assert {"code": "ttps", "points": 6} in article.score_reasons["priority"]
    assert article.llm_ttp_status == "done"


def _stored(session: Session) -> Article:
    article = session.scalar(select(Article).where(Article.url_hash == url_hash(URL)))
    assert article is not None
    return article


def test_pipeline_stores_capped_summary(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    long_text = "Kalimat uji nomor satu. " * 100
    monkeypatch.setattr(pipeline, "summarize", lambda text: long_text)
    _seed(session)

    _run(session)

    summary = _stored(session).summary
    assert summary == make_dek(long_text)
    assert summary is not None and len(summary) <= 601 and summary.endswith(".")


def test_persist_keeps_summary_when_none(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(session)
    _run(session)
    assert _stored(session).summary == "Ringkasan."

    monkeypatch.setattr(pipeline, "summarize", lambda text: "")
    _run(session)

    assert _stored(session).summary == "Ringkasan."


def test_pipeline_stores_summary_on_best_practice_branch(session: Session) -> None:
    _seed(session)
    verdict = ClassifyResult(
        related_cyber=True,
        confidence=0.9,
        reason="hardening guide",
        industries_impacted=["General"],
        security_tech_best_practice=True,
        audit={"model": "stub"},
    )

    run_with_verdict(
        session,
        verdict,
        title="Hardening guide",
        url=URL,
        posted_on=None,
        source="Test",
        scraper_id="t",
    )

    article = _stored(session)
    assert article.news_type == "Security Technology & Best Practices"
    assert article.summary == "Ringkasan."
