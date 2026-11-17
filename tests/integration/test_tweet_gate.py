"""Gate relevansi tweet (spec tweet-llm-cost, Part C) terhadap Postgres REAL: job `tweet` lewat
`jobs.run_job` dengan model tweet aktif (FakeEmbedder), `gate_stats(kind="tweet")` dari
`tweet_verdicts`, dan `relevance.evaluate` yang menggeser gate tweet terpisah dari gate artikel.
LLM (`classify_tweet`) dan Telegram di-patch."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from cti_core.db.engine import sync_session
from cti_core.db.models.article import Article, RejectedArticle
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.models.relevance import RelevanceModel
from cti_core.db.models.tweet_verdict import TweetVerdict
from cti_core.db.repositories.relevance import RelevanceModelRepo
from cti_core.db.repositories.tweet import TweetVerdictRepo
from cti_enrich import jobs, tweet_job
from cti_enrich.relevance import model as model_mod
from cti_enrich.relevance.embedder import set_embedder
from cti_enrich.relevance.model import KIND_CLASSES, Example, dumps, fit
from cti_enrich.stages import relevance as stage
from cti_enrich.stages.classify import ClassifyResult
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tests.integration.test_tweet_jobs import NOW, VERDICT, make_job, stored, verdict
from tests.unit.relevance_fakes import FakeEmbedder

TEXT = "Hospital Acme confirms ransomware attack, systems encrypted"
THREAT = ["hospital", "confirms", "ransomware", "attack", "systems", "encrypted", "breach"]
NOISE = ["coffee", "webinar", "giveaway", "football", "holiday", "concert", "podcast"]


def _tweet_model() -> bytes:
    def ex(words: list[str], label: str, i: int) -> Example:
        text = " ".join(words[(i + k) % len(words)] for k in range(4))
        return Example(f"{text} n{i}", label, NOW)

    examples = [ex(THREAT, "threat_news", i) for i in range(40)]
    examples += [ex(NOISE, "reject", i) for i in range(40)]
    return dumps(fit(examples, FakeEmbedder(), KIND_CLASSES["tweet"]))


def _model_row(kind: str, gate_state: str, artifact: bytes = b"x") -> RelevanceModel:
    return RelevanceModel(
        kind=kind, status="active", artifact=artifact,
        feature_version=model_mod.feature_version(FakeEmbedder()), n_examples=80,
        class_counts={}, metrics={}, gate_state=gate_state,
    )  # fmt: skip


def _relevance_cfg(monkeypatch: pytest.MonkeyPatch, **values: Any) -> None:
    from cti_core.config import get_settings

    for key, value in {"mode": "auto", "audit_rate": 0.0, **values}.items():
        monkeypatch.setattr(get_settings().relevance, key, value)


@pytest.fixture(autouse=True)
def _fresh_stage() -> Iterator[None]:
    set_embedder(FakeEmbedder())
    stage._reset_cache()
    yield
    set_embedder(None)
    stage._reset_cache()


@pytest.fixture
def session(_migrated_schema: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Satu sesi (savepoint) untuk test DAN job runner, di-rollback di akhir (pola
    `test_tweet_jobs`)."""
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    s.execute(delete(EnrichJob))
    s.execute(delete(RelevanceModel))

    @contextmanager
    def _shared() -> Iterator[Session]:
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise

    monkeypatch.setattr(jobs, "sync_session", _shared)
    monkeypatch.setattr(tweet_job, "sync_session", _shared)
    monkeypatch.setattr(tweet_job, "send_alert", lambda topic, text: None)
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


# ── job tweet ───────────────────────────────────────────────────────────────────────────────


def test_gated_tweet_skips_llm_and_fills_tier1_fields(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_llm(text: str) -> ClassifyResult:
        raise AssertionError("LLM tidak boleh dipanggil untuk tweet yang lolos gate")

    monkeypatch.setattr(tweet_job, "classify_tweet", no_llm)
    _relevance_cfg(monkeypatch)
    session.add(_model_row("tweet", "gate", _tweet_model()))
    job_id = make_job(session, text=TEXT)

    assert jobs.run_job(job_id, now=NOW) == "done"

    v = verdict(session)
    assert v is not None and v.source == "gate" and v.prompt_version is None
    assert v.relevance is not None
    assert (v.relevance["decision"], v.relevance["in_band"]) == ("gated", True)
    assert v.relevance["incident_source"] == "rule"
    tweet = stored(session)
    assert tweet is not None
    assert tweet.industries_impacted == ["Healthcare & Life Sciences"]
    assert tweet.confirmed_incident is True
    assert tweet.victim_name == "Hospital Acme"  # korban Tier 1 karena insiden terkonfirmasi
    assert tweet.victim_countries == [] and tweet.actor_countries == []
    assert tweet.confidence_score is not None and tweet.confidence_score >= 85


def test_shadow_tweet_model_still_calls_llm_and_records_relevance(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(tweet_job, "classify_tweet", lambda text: seen.append(text) or VERDICT)
    _relevance_cfg(monkeypatch)
    session.add(_model_row("tweet", "shadow", _tweet_model()))
    job_id = make_job(session, text=TEXT)

    assert jobs.run_job(job_id, now=NOW) == "done"

    assert seen == [TEXT]
    v = verdict(session)
    assert v is not None and v.source == "llm"
    assert v.relevance is not None
    assert (v.relevance["decision"], v.relevance["in_band"]) == ("shadow", True)
    assert v.relevance["probs"]["best_practice"] == 0.0
    tweet = stored(session)
    assert tweet is not None and tweet.victim_countries == ["Indonesia"]


def test_article_model_is_not_used_for_tweets(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hanya model `article` yang aktif (state gate): tweet tetap ke LLM tanpa audit relevansi."""
    seen: list[str] = []
    monkeypatch.setattr(tweet_job, "classify_tweet", lambda text: seen.append(text) or VERDICT)
    _relevance_cfg(monkeypatch)
    session.add(_model_row("article", "gate", _tweet_model()))
    job_id = make_job(session, text=TEXT)

    assert jobs.run_job(job_id, now=NOW) == "done"

    v = verdict(session)
    assert seen == [TEXT] and v is not None and v.source == "llm" and v.relevance is None


# ── gate_stats(kind="tweet") ────────────────────────────────────────────────────────────────


def _rel(decision: str, in_band: bool = True) -> dict[str, Any]:
    return {"model_id": 1, "probs": {}, "in_band": in_band, "decision": decision}


def test_gate_stats_for_tweets_reads_llm_verdicts(db_session: Session) -> None:
    db_session.execute(delete(TweetVerdict))
    repo = TweetVerdictRepo(db_session)
    rows: list[tuple[str, bool, str, dict[str, Any] | None]] = [
        ("agree", True, "llm", _rel("shadow")),
        ("disagree", False, "llm", _rel("shadow")),
        ("audit", True, "llm", _rel("audit")),
        ("out", True, "llm", _rel("llm", in_band=False)),
        ("gated", True, "gate", _rel("gated")),
        ("none", True, "llm", None),  # tersimpan sebagai JSON null
    ]
    for tid, related, source, relevance in rows:
        repo.record(
            tweet_id=tid, text=tid, related_cyber=related, source=source,
            prompt_version=None, relevance=relevance,
        )  # fmt: skip
    db_session.flush()

    stats = RelevanceModelRepo(db_session).gate_stats(
        since=NOW - dt.timedelta(days=14), revert_samples=5, kind="tweet"
    )

    assert (stats.band_n, stats.band_agree, stats.audit_last) == (3, 2, [True])


# ── relevance.evaluate per kind ────────────────────────────────────────────────────────────


@pytest.fixture
def clean(_migrated_schema: None) -> Iterator[None]:
    def wipe() -> None:
        with sync_session() as s:
            s.execute(delete(Article))
            s.execute(delete(RejectedArticle))
            s.execute(delete(RelevanceModel))
            s.execute(delete(TweetVerdict))

    wipe()
    yield
    wipe()


def _gate_state(model_id: int) -> str:
    with sync_session() as s:
        return s.execute(
            select(RelevanceModel.gate_state).where(RelevanceModel.id == model_id)
        ).scalar_one()


def test_evaluate_moves_tweet_gate_independently_of_article_gate(
    clean: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cti_worker.tasks import relevance as mod

    with sync_session() as s:
        article, tweet = _model_row("article", "shadow"), _model_row("tweet", "shadow")
        s.add_all([article, tweet])
        s.flush()
        article_id, tweet_id = article.id, tweet.id
        repo = TweetVerdictRepo(s)
        for i in range(200):  # 200 tweet dalam band, semua disetujui LLM
            repo.record(
                tweet_id=f"t{i}", text=f"t{i}", related_cyber=True, source="llm",
                prompt_version=None, relevance=_rel("shadow"),
            )  # fmt: skip
    _relevance_cfg(monkeypatch, audit_rate=0.2)
    monkeypatch.setattr(model_mod, "loads", lambda data: object())
    monkeypatch.setattr(stage, "needs_retrain", lambda session, kind="article": False)
    monkeypatch.setattr(mod.train, "delay", lambda *a, **kw: pytest.fail("train tidak dipicu"))
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mod, "alert_ops", lambda text, *, key, cooldown_s=3600: sent.append((key, text))
    )

    out = mod.evaluate()

    assert out["action"] == "none" and out["state"] == "shadow"
    assert out["tweet"]["action"] == "changed" and out["tweet"]["state"] == "gate"
    assert _gate_state(article_id) == "shadow"
    assert _gate_state(tweet_id) == "gate"
    assert [k for k, _ in sent] == ["relevance:gate:tweet:gate"]
    assert "tweet" in sent[0][1]
