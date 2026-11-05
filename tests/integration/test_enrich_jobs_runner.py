"""Job runner `cti_enrich.jobs.run_job` (P7g Task 4, spec 4.3) terhadap Postgres REAL.

LLM di-patch di `cti_enrich.jobs.classify` / `.extract_ttps`; stage berat pipeline (fetch,
summarize, IOC, score) di-stub, `persist`/Tier 1/`apply_ttps`/P6 asli. `run_job` membuka
`sync_session()` sendiri; di sini diarahkan ke sesi test (`share_session`) supaya semua commit-nya
hanya SAVEPOINT dan di-rollback di akhir test.

Review Focus yang dikunci: (2) job dijalankan dua kali = satu artikel, satu alert; (3) keputusan
analis atau artikel terhapus selagi panggilan LLM berjalan = yang commit duluan menang, yang lain
no-op tanpa error; (4) baris migrasi (`input_text IS NULL`) untuk URL yang sudah jadi artikel
= duplikat, dan yang beritanya lama disimpan tanpa alert.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterator
from typing import Any

import httpx
import openai
import pytest
import sqlalchemy.exc
from cti_core.db.models.article import Article, RejectedArticle
from cti_core.db.models.attack import AttackTechnique
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.models.story import Story
from cti_core.db.repositories.article import ArticleRepo
from cti_core.db.repositories.enrich_job import EnrichJobRepo
from cti_core.entity.mentions import MentionInput
from cti_core.urlkit import url_hash
from cti_enrich import jobs, pipeline
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.extract_ttps import Technique, TtpResult
from cti_enrich.stages.score import ScoreResult
from cti_enrich.stages.tier1 import Tier1Result
from cti_enrich.story.attach import classify_to_story
from cti_enrich.tier1.incident import IncidentVerdict
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tests.integration.enrich_job_support import job_for, share_session
from tests.integration.entity_support import seed_entity

URL = "https://example.com/jobs-runner/report-1"
TITLE = "Ransomware gang hits regional hospital"
BODY = "The hospital confirmed a ransomware attack this week. Systems were encrypted. " * 3
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=datetime.UTC)
TODAY = NOW.date()
OLD = TODAY - datetime.timedelta(days=3)
CTX: dict[str, Any] = {
    "story": None,
    "relevance": None,
    "content_kind": None,
    "default_relevance": "classify",
    "tlp": "clear",
    "pap": "clear",
}
VERDICT = ClassifyResult(
    related_cyber=True,
    confidence=0.9,
    reason="ransomware",
    industries_impacted=["Healthcare"],
    audit={"model": "stub"},
)
_REQ = httpx.Request("POST", "http://gw/v1/chat/completions")


@pytest.fixture
def session(_migrated_schema: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    share_session(monkeypatch, s)
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    sent: list[object] = []
    monkeypatch.setattr(pipeline, "route_alerts", lambda result: sent.append(result))
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: BODY)
    monkeypatch.setattr(pipeline, "resolve_story", lambda **kw: None)
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())
    return sent


def no_llm(*args: object, **kwargs: object) -> Any:
    raise AssertionError("LLM tidak boleh dipanggil")


def _classify_job(
    session: Session,
    *,
    posted_on: datetime.date | None = TODAY,
    input_text: str | None = BODY,
    context: dict[str, Any] | None = None,
) -> int:
    job = EnrichJobRepo(session).create(
        kind="classify",
        url=URL,
        title=TITLE,
        source="Test",
        scraper_id="t",
        posted_on=posted_on,
        input_text=input_text,
        context=CTX if context is None else context,
    )
    assert job is not None
    session.commit()
    return job.id


def _article(session: Session) -> Article | None:
    return session.scalar(select(Article).where(Article.url_hash == url_hash(URL)))


def _articles(session: Session) -> int:
    return session.scalar(
        select(func.count()).select_from(Article).where(Article.url_hash == url_hash(URL))
    )


def _job(session: Session, job_id: int) -> EnrichJob | None:
    return session.get(EnrichJob, job_id, populate_existing=True)


# ── classify ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("posted_on", "alerted"), [(TODAY, 1), (OLD, 0)])
def test_classify_job_accepts_and_alerts_if_fresh(
    session: Session,
    alerts: list[object],
    monkeypatch: pytest.MonkeyPatch,
    posted_on: datetime.date,
    alerted: int,
) -> None:
    job_id = _classify_job(session, posted_on=posted_on)
    monkeypatch.setattr(jobs, "classify", lambda title: VERDICT)

    assert jobs.run_job(job_id, now=NOW) == "done"

    assert _job(session, job_id) is None
    article = _article(session)
    assert article is not None and article.raw_enrichment["classify"] == {"model": "stub"}
    assert len(alerts) == alerted
    # TTP LLM menyusul lewat job `ttp` (teks yang PERSIS dikirim ke model).
    ttp = job_for(session, URL, "ttp")
    assert ttp is not None and ttp.article_id == article.id and ttp.input_text == BODY
    assert article.llm_ttp_status == "pending"


@pytest.mark.parametrize(
    ("age_days", "alerted"), [(0, 1), (3, 0)], ids=["created-now", "created-3-days-ago"]
)
def test_dateless_classify_job_freshness_follows_created_at(
    session: Session,
    alerts: list[object],
    monkeypatch: pytest.MonkeyPatch,
    age_days: int,
    alerted: int,
) -> None:
    """R13: tanpa `posted_on`, kesegaran = `created_at` job (kedatangan live alert, baris migrasi
    dengan `created_at` lama = `rejected_at` tidak)."""
    job_id = _classify_job(session, posted_on=None)
    job = _job(session, job_id)
    assert job is not None
    job.created_at = NOW - datetime.timedelta(days=age_days)
    session.commit()
    monkeypatch.setattr(jobs, "classify", lambda title: VERDICT)

    assert jobs.run_job(job_id, now=NOW) == "done"

    assert _article(session) is not None
    assert len(alerts) == alerted


def test_classify_job_rejects_to_rejected_articles(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _classify_job(session)
    monkeypatch.setattr(
        jobs, "classify", lambda title: ClassifyResult(related_cyber=False, reason="not cyber")
    )

    assert jobs.run_job(job_id, now=NOW) == "done"

    assert _job(session, job_id) is None
    assert _article(session) is None
    rejected = session.scalar(
        select(RejectedArticle).where(RejectedArticle.url_hash == url_hash(URL))
    )
    assert rejected is not None and rejected.reason == "not cyber"
    assert alerts == []


def test_classify_job_inherits_when_lead_classified_meanwhile(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    story = Story(
        title="Lead story",
        lead_source="Other",
        cve_ids=[],
        first_seen_at=NOW,
        last_seen_at=NOW,
        article_count=0,
        source_count=0,
    )
    session.add(story)
    session.flush()
    link = {
        "story_id": story.id,
        "rule": "title",
        "inherited": None,
        "lead_article_id": None,
        "cve_ids": [],
    }
    job_id = _classify_job(session, context={**CTX, "story": link})
    # Lead-nya selesai di-classify SESUDAH job ini dibuat.
    story.classify = classify_to_story(VERDICT)
    session.commit()
    monkeypatch.setattr(jobs, "classify", no_llm)

    assert jobs.run_job(job_id, now=NOW) == "done"

    article = _article(session)
    assert article is not None
    assert article.raw_enrichment["classify"]["inherited_from_story"] == story.id
    assert article.story_id == story.id
    # Warisan story tidak memakai LLM TTP (TTP milik lead).
    assert article.llm_ttp_status == "skipped"
    assert job_for(session, URL, "ttp") is None


def test_job_without_text_runs_prepare_first(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Baris migrasi (`context={}`, `input_text=NULL`) dengan `posted_on` lama: fetch dulu, lalu
    LLM, artikel disimpan TANPA alert (Review Focus 4)."""
    fetched: list[str] = []
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: fetched.append(url) or BODY)
    job_id = _classify_job(session, posted_on=OLD, input_text=None, context={})
    monkeypatch.setattr(jobs, "classify", lambda title: VERDICT)

    assert jobs.run_job(job_id, now=NOW) == "done"

    assert fetched == [URL]
    assert _article(session) is not None
    assert _job(session, job_id) is None
    assert alerts == []
    ttp = job_for(session, URL, "ttp")
    assert ttp is not None and ttp.input_text == BODY


def test_migrated_tier0_row_completes_without_llm(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R7: `context` tanpa `default_relevance` -> `relevance_for(scraper_id)`; Tier 0 tanpa LLM."""
    job_id = _classify_job(session, input_text=None, context={})
    monkeypatch.setattr(jobs, "classify", no_llm)
    asked: list[str | None] = []

    def relevance_for(scraper_id: str | None) -> tuple[str | None, str, str, str]:
        asked.append(scraper_id)
        return "advisory", "always", "green", "clear"

    assert jobs.run_job(job_id, now=NOW, relevance_for=relevance_for) == "done"

    assert asked == ["t"]
    article = _article(session)
    assert article is not None
    assert article.raw_enrichment["classify"]["skipped"] == "default_relevance=always"
    assert article.llm_ttp_status == "skipped"
    assert len(alerts) == 1


def test_migrated_row_for_existing_article_is_duplicate(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    article = ArticleRepo(session).upsert(url=URL, title=TITLE, source="Test")
    session.commit()
    job_id = _classify_job(session, input_text=None, context={})
    monkeypatch.setattr(jobs, "classify", no_llm)
    monkeypatch.setattr(pipeline, "fetch_text", no_llm)

    assert jobs.run_job(job_id, now=NOW) == "duplicate"

    assert _job(session, job_id) is None
    session.refresh(article)
    assert article.seen_count == 1  # bukan kedatangan baru
    assert alerts == []


# ── kegagalan ──────────────────────────────────────────────────────────────────────────────


def test_gateway_error_reschedules_without_cap(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _classify_job(session)
    failed: list[tuple[str, str]] = []

    def down(title: str) -> ClassifyResult:
        raise openai.InternalServerError(
            "upstream down", response=httpx.Response(503, request=_REQ), body=None
        )

    monkeypatch.setattr(jobs, "classify", down)

    assert jobs.run_job(job_id, now=NOW, on_failed=lambda *a: failed.append(a)) == "retry"
    job = _job(session, job_id)
    assert job is not None
    assert (job.attempts, job.state) == (1, "pending")
    assert job.next_attempt_at == NOW + datetime.timedelta(minutes=2)
    assert job.last_error is not None and job.last_error.startswith("InternalServerError: ")

    for _ in range(10):
        assert jobs.run_job(job_id, now=NOW, on_failed=lambda *a: failed.append(a)) == "retry"
    job = _job(session, job_id)
    assert job is not None
    assert (job.attempts, job.state) == (11, "pending")
    assert job.next_attempt_at == NOW + datetime.timedelta(minutes=60)
    assert failed == []
    assert _article(session) is None


def test_json_error_fails_after_three(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _classify_job(session)
    failed: list[tuple[str, str]] = []

    def broken(_: str) -> Any:
        raise json.JSONDecodeError("Expecting value", "<think>", 0)

    monkeypatch.setattr(jobs, "classify", broken)

    outcomes = [
        jobs.run_job(job_id, now=NOW, on_failed=lambda *a: failed.append(a)) for _ in range(3)
    ]

    assert outcomes == ["retry", "retry", "failed"]
    job = _job(session, job_id)
    assert job is not None and (job.state, job.json_failures) == ("failed", 3)
    assert len(failed) == 1 and failed[0][0] == TITLE
    assert failed[0][1].startswith("JSONDecodeError: ")

    # Job `ttp`: batas JSON = job dihapus, artikel tetap dengan TTP Tier 1 (`failed`).
    article = ArticleRepo(session).upsert(
        url="https://example.com/jobs-runner/ttp", title="t", source="s", llm_ttp_status="pending"
    )
    ttp = EnrichJobRepo(session).create(
        kind="ttp",
        url=article.url,
        title="t",
        source="s",
        scraper_id=None,
        posted_on=None,
        input_text=BODY,
        context={},
        article_id=article.id,
    )
    assert ttp is not None
    session.commit()
    monkeypatch.setattr(jobs, "extract_ttps", broken)

    outcomes = [jobs.run_job(ttp.id, now=NOW) for _ in range(3)]

    assert outcomes == ["retry", "retry", "failed"]
    assert _job(session, ttp.id) is None
    session.refresh(article)
    assert article.llm_ttp_status == "failed"


def test_unexpected_error_marks_failed(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    from cti_core.runtime_secrets import overlay

    monkeypatch.setattr(overlay, "scrub_candidates", lambda: ["sk-very-secret"])
    job_id = _classify_job(session)
    failed: list[tuple[str, str]] = []

    def bug(_: str) -> Any:
        raise RuntimeError("bug near sk-very-secret")

    monkeypatch.setattr(jobs, "classify", bug)

    assert jobs.run_job(job_id, now=NOW, on_failed=lambda *a: failed.append(a)) == "failed"

    job = _job(session, job_id)
    assert job is not None and job.state == "failed"
    assert job.last_error == "RuntimeError: bug near ***"
    assert failed == [(TITLE, "RuntimeError: bug near ***")]
    # Job `failed` menunggu analis: kiriman lain (lease habis) tidak menjalankannya lagi.
    assert jobs.run_job(job_id, now=NOW, on_failed=lambda *a: failed.append(a)) == "failed"
    assert len(failed) == 1


# ── TTP ──────────────────────────────────────────────────────────────────────────────────


TTP_TEXT = (
    "The intruders sent spear-phishing emails with malicious attachments to finance staff. "
    "A PowerShell loader then ran on the first host."
)


def test_ttp_job_merges_and_keeps_analyst(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    session.add_all(
        [
            AttackTechnique(
                stix_id=f"attack-pattern--{tid}",
                attack_id=tid,
                name=name,
                tactics=[],
                domains=["enterprise-attack"],
                is_subtechnique=False,
                parent_id=None,
            )
            for tid, name in [
                ("T1059", "Command and Scripting Interpreter"),
                ("T1566", "Phishing"),
                ("T1027", "Obfuscated Files or Information"),
                ("T1105", "Ingress Tool Transfer"),
            ]
        ]
    )
    seed_entity(session, "attack-pattern", "Command and Scripting Interpreter", external_id="T1059")
    seed_entity(session, "attack-pattern", "Phishing", external_id="T1566")
    seed_entity(session, "attack-pattern", "Ingress Tool Transfer", external_id="T1105")
    repo = ArticleRepo(session)
    article = repo.upsert(url=URL, title=TITLE, source="Test", llm_ttp_status="pending")
    repo.add_mentions(
        article,
        [
            MentionInput(
                "attack-pattern",
                "Command and Scripting Interpreter",
                "analyst",
                "PowerShell loader",  # alias khusus analis, BUKAN ID teknik
                evidence="analyst note",
                external_id="T1059",
            ),
            MentionInput(
                "attack-pattern",
                "Ingress Tool Transfer",
                "legacy",
                "T1105",
                evidence="legacy row",
                external_id="T1105",
            ),
            MentionInput(
                "attack-pattern",
                "Phishing",
                "keyword",
                "T1566",
                evidence="spear-phishing",
                external_id="T1566",
            ),
        ],
    )
    job = EnrichJobRepo(session).create(
        kind="ttp",
        url=URL,
        title=TITLE,
        source="Test",
        scraper_id="t",
        posted_on=TODAY,
        input_text=TTP_TEXT,
        context={},
        article_id=article.id,
    )
    assert job is not None
    session.commit()
    monkeypatch.setattr(jobs, "classify", no_llm)
    monkeypatch.setattr(
        jobs,
        "extract_ttps",
        lambda text: TtpResult(
            has_techniques=True,
            techniques=[
                Technique("T1566", "Phishing", evidence="sent spear-phishing emails"),
                Technique("T1027", "Obfuscated Files or Information", evidence="packed with UPX"),
                Technique("T1059", "Command and Scripting Interpreter", evidence="PowerShell"),
                Technique("T1105", "Ingress Tool Transfer", evidence="PowerShell loader"),
            ],
        ),
    )

    def rows() -> dict[str, tuple[Any, ...]]:
        session.expire(article)
        return {
            m.entity.external_id: (m.id, m.method, m.matched_alias, m.evidence, m.extracted)
            for m in article.mentions_of("attack-pattern")
        }

    before = rows()

    assert jobs.run_job(job.id, now=NOW) == "done"

    assert _job(session, job.id) is None
    after = rows()
    # Mention analis dan legacy tidak disentuh sama sekali (id, alias, method, bukti tetap),
    # walau LLM mengusulkan ID yang sama dengan bukti yang valid.
    assert after["T1059"] == before["T1059"]
    assert after["T1059"][1:4] == ("analyst", "PowerShell loader", "analyst note")
    assert after["T1105"] == before["T1105"]
    assert {tid: row[1] for tid, row in after.items()} == {
        "T1059": "analyst",
        "T1105": "legacy",
        "T1566": "llm",
    }
    assert after["T1566"][3] == "sent spear-phishing emails"
    session.refresh(article)
    assert article.llm_ttp_status == "done"
    assert article.priority_score is not None
    assert article.score_reasons is not None
    assert {"code": "ttps", "points": 3} in article.score_reasons["priority"]
    assert alerts == []


def test_ttp_job_for_deleted_article_is_gone(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    article = ArticleRepo(session).upsert(
        url=URL, title=TITLE, source="Test", llm_ttp_status="pending"
    )
    job = EnrichJobRepo(session).create(
        kind="ttp",
        url=URL,
        title=TITLE,
        source="Test",
        scraper_id="t",
        posted_on=TODAY,
        input_text=TTP_TEXT,
        context={},
        article_id=article.id,
    )
    assert job is not None
    session.commit()
    job_id, article_id = job.id, article.id

    def delete_meanwhile(text: str) -> TtpResult:
        # Analis menghapus artikelnya selagi panggilan LLM berjalan (job ikut, CASCADE).
        session.execute(delete(Article).where(Article.id == article_id))
        session.commit()
        return TtpResult(has_techniques=False)

    monkeypatch.setattr(jobs, "extract_ttps", delete_meanwhile)

    assert jobs.run_job(job_id, now=NOW) == "gone"
    assert jobs.run_job(job_id, now=NOW) == "gone"


# ── balapan (Review Focus 2/3) dan keputusan analis ──────────────────────────────────────


def test_run_job_twice_creates_one_article(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kiriman kedua (lease habis) jalan selagi panggilan LLM kiriman pertama berjalan."""
    job_id = _classify_job(session)
    calls: list[str] = []

    def llm(title: str) -> ClassifyResult:
        calls.append(title)
        if len(calls) == 1:
            assert jobs.run_job(job_id, now=NOW) == "done"
        return VERDICT

    monkeypatch.setattr(jobs, "classify", llm)

    assert jobs.run_job(job_id, now=NOW) == "gone"
    assert jobs.run_job(job_id, now=NOW) == "gone"

    assert _articles(session) == 1
    assert len(alerts) == 1


def test_analyst_decision_vs_inflight_llm(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _classify_job(session)

    def llm(title: str) -> ClassifyResult:
        assert jobs.run_job(job_id, decision="accept", now=NOW) == "done"
        return ClassifyResult(related_cyber=False, reason="llm says no")

    monkeypatch.setattr(jobs, "classify", llm)

    assert jobs.run_job(job_id, now=NOW) == "gone"

    assert _articles(session) == 1
    article = _article(session)
    assert article is not None and article.raw_enrichment["classify"] == {"skipped": "analyst"}
    assert (
        session.scalar(
            select(func.count())
            .select_from(RejectedArticle)
            .where(RejectedArticle.url_hash == url_hash(URL))
        )
        == 0
    )


def test_accept_decision_uses_rule_incident(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _classify_job(session)
    monkeypatch.setattr(jobs, "classify", no_llm)
    monkeypatch.setattr(
        pipeline,
        "run_tier1",
        lambda **kw: Tier1Result(incident=IncidentVerdict(True, ("ransomware",), victim="Acme")),
    )

    assert jobs.run_job(job_id, decision="accept", now=NOW) == "done"

    article = _article(session)
    assert article is not None
    assert article.confirmed_incident is True
    assert article.victim_name == "Acme"
    assert article.raw_enrichment["classify"] == {"skipped": "analyst"}
    assert _job(session, job_id) is None


def test_reject_decision_reason_analyst(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _classify_job(session)
    monkeypatch.setattr(jobs, "classify", no_llm)

    assert jobs.run_job(job_id, decision="reject", now=NOW) == "done"

    assert _article(session) is None
    rejected = session.scalar(
        select(RejectedArticle).where(RejectedArticle.url_hash == url_hash(URL))
    )
    assert rejected is not None and rejected.reason == "analyst"
    assert rejected.raw_enrichment["classify"] == {"skipped": "analyst"}
    assert _job(session, job_id) is None
    assert alerts == []


def test_decision_on_a_ttp_job_is_refused_without_failing_it(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    article = ArticleRepo(session).upsert(
        url=URL, title=TITLE, source="Test", llm_ttp_status="pending"
    )
    job = EnrichJobRepo(session).create(
        kind="ttp",
        url=URL,
        title=TITLE,
        source="Test",
        scraper_id="t",
        posted_on=TODAY,
        input_text=TTP_TEXT,
        context={},
        article_id=article.id,
    )
    assert job is not None
    session.commit()
    monkeypatch.setattr(jobs, "extract_ttps", no_llm)

    with pytest.raises(jobs.DecisionNotAllowed):
        jobs.run_job(job.id, decision="accept", now=NOW)

    after = _job(session, job.id)
    assert after is not None and after.state == "pending" and after.last_error is None


def test_db_error_reschedules_like_gateway(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R9: putus DB/jaringan bukan bug per job: dijadwalkan ulang, tidak `failed`, tanpa alert."""
    job_id = _classify_job(session, input_text=None, context={})
    failed: list[tuple[str, str]] = []

    def db_down(url: str) -> str:
        raise sqlalchemy.exc.OperationalError("SELECT 1", {}, Exception("server closed"))

    monkeypatch.setattr(pipeline, "fetch_text", db_down)
    monkeypatch.setattr(jobs, "classify", no_llm)

    assert jobs.run_job(job_id, now=NOW, on_failed=lambda *a: failed.append(a)) == "retry"

    job = _job(session, job_id)
    assert job is not None
    assert (job.state, job.attempts, job.input_text) == ("pending", 1, None)
    assert job.last_error is not None and job.last_error.startswith("OperationalError: ")
    assert failed == []
