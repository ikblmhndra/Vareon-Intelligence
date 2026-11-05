"""EnrichJobRepo (P7g): unik per (kind, url), klaim + lease, backoff, batas JSON, cascade."""

from __future__ import annotations

import datetime

from cti_core.db.models.article import Article
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.repositories.enrich_job import EnrichJobRepo
from cti_core.urlkit import url_hash
from sqlalchemy.orm import Session

NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=datetime.UTC)


def _make(repo: EnrichJobRepo, url: str, kind: str = "classify", **kw):  # type: ignore[no-untyped-def]
    return repo.create(
        kind=kind,
        url=url,
        title="t",
        source="s",
        scraper_id=None,
        posted_on=None,
        input_text=None,
        context={},
        **kw,
    )


def test_create_is_unique_per_kind_and_url(db_session: Session) -> None:
    repo = EnrichJobRepo(db_session)
    first = _make(repo, "https://example.com/a")
    assert first is not None and first.id
    assert _make(repo, "https://example.com/a") is None
    assert _make(repo, "https://example.com/a", kind="ttp") is not None
    assert repo.has_classify(url_hash("https://example.com/a"))
    assert not repo.has_classify(url_hash("https://example.com/zzz"))


def test_claim_due_orders_classify_first_and_sets_lease(db_session: Session) -> None:
    repo = EnrichJobRepo(db_session)
    ttp = _make(repo, "https://example.com/t", kind="ttp")
    c1 = _make(repo, "https://example.com/c1")
    c2 = _make(repo, "https://example.com/c2")
    assert ttp and c1 and c2
    ttp.created_at = NOW - datetime.timedelta(hours=3)
    ttp.next_attempt_at = NOW - datetime.timedelta(minutes=1)  # jatuh tempo relatif NOW
    c1.created_at = NOW - datetime.timedelta(hours=2)
    c1.next_attempt_at = NOW - datetime.timedelta(minutes=1)  # jatuh tempo relatif NOW
    c2.created_at = NOW - datetime.timedelta(hours=1)
    c2.next_attempt_at = NOW - datetime.timedelta(minutes=1)  # jatuh tempo relatif NOW
    db_session.flush()
    lease = datetime.timedelta(minutes=15)

    got = repo.claim_due(NOW, limit=2, lease=lease)
    assert [j.id for j in got] == [c1.id, c2.id]
    assert all(j.next_attempt_at == NOW + lease for j in got)

    again = repo.claim_due(NOW, limit=2, lease=lease)
    assert [j.id for j in again] == [ttp.id]


def test_gateway_backoff(db_session: Session) -> None:
    repo = EnrichJobRepo(db_session)
    job = _make(repo, "https://example.com/g")
    assert job
    repo.record_gateway_failure(job, NOW, "boom")
    assert job.attempts == 1
    assert job.next_attempt_at == NOW + datetime.timedelta(minutes=2)
    assert job.last_error == "boom"
    job.attempts = 7
    repo.record_gateway_failure(job, NOW, "x" * 500)
    assert job.attempts == 8
    assert job.next_attempt_at == NOW + datetime.timedelta(minutes=60)
    assert len(job.last_error or "") == 300


def test_json_cap(db_session: Session) -> None:
    repo = EnrichJobRepo(db_session)
    job = _make(repo, "https://example.com/j")
    assert job
    assert repo.record_json_failure(job, NOW, "bad") is False
    assert repo.record_json_failure(job, NOW, "bad") is False
    assert job.state == "pending"
    assert repo.record_json_failure(job, NOW, "bad") is True
    assert job.state == "failed"
    counts = repo.counts()
    assert counts.failed >= 1


def test_job_deleted_with_article(db_session: Session) -> None:
    article = Article(
        url="https://example.com/art",
        url_hash=url_hash("https://example.com/art"),
        title="t",
        source="s",
    )
    db_session.add(article)
    db_session.flush()
    repo = EnrichJobRepo(db_session)
    job = _make(repo, "https://example.com/art", kind="ttp", article_id=article.id)
    assert job
    job_id = job.id
    db_session.delete(article)
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(EnrichJob, job_id) is None
