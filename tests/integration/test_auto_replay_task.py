"""Task `enrich.auto_replay` dan `llm.purge_calls` di Postgres beneran (testcontainers).

Task membuka `sync_session()` sendiri dan commit, jadi baris seed dibersihkan manual."""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import pytest
from cti_core.db.engine import sync_session
from cti_core.db.models.article import RejectedArticle
from cti_core.db.models.llm_call import LlmCall
from cti_core.urlkit import url_hash
from sqlalchemy import delete, select

PREFIX = "https://example.com/auto-replay/"
MODEL = "auto-replay-test"
TODAY = datetime.datetime.now(datetime.UTC).date()


@pytest.fixture(autouse=True)
def _clean(_migrated_schema: None) -> Iterator[None]:
    def wipe() -> None:
        with sync_session() as s:
            s.execute(delete(RejectedArticle).where(RejectedArticle.url.like(f"{PREFIX}%")))
            s.execute(delete(LlmCall).where(LlmCall.model == MODEL))

    wipe()
    yield
    wipe()


@pytest.fixture
def mod(_migrated_schema: None):
    # Import LAZY: `cti_worker.celery_app` baca settings + DB pas di-import.
    from cti_worker.tasks import llm_maintenance

    return llm_maintenance


def _llm_call(at: datetime.datetime, status: str = "ok") -> None:
    with sync_session() as s:
        s.add(LlmCall(at=at, task="classify", model=MODEL, status=status, latency_ms=10))


def _park(name: str, kind: str, posted_on: datetime.date | None) -> None:
    url = f"{PREFIX}{name}"
    with sync_session() as s:
        s.add(
            RejectedArticle(
                url=url,
                url_hash=url_hash(url),
                title=name,
                source="Test",
                scraper_id="t",
                posted_on=posted_on,
                failure_kind=kind,
                raw_enrichment={},
            )
        )


def _rows() -> dict[str, RejectedArticle]:
    with sync_session() as s:
        rows = s.execute(
            select(RejectedArticle).where(RejectedArticle.url.like(f"{PREFIX}%"))
        ).scalars()
        return {r.title: r for r in rows}


def test_auto_replay_sends_and_marks(mod, monkeypatch: pytest.MonkeyPatch) -> None:
    _llm_call(datetime.datetime.now(datetime.UTC))
    _park("transient", "transient", TODAY)
    _park("config", "config", TODAY - datetime.timedelta(days=5))
    _park("permanent", "permanent", TODAY)
    sent: list[dict] = []
    monkeypatch.setattr("cti_core.celery_client.send_enrich_task", lambda **kw: sent.append(kw))
    monkeypatch.setattr("cti_scraper.sinks.enrich_queue_depth", lambda: 0)

    result = mod.auto_replay()

    assert result == {"sent": 2, "failed": 0}
    assert {kw["title"]: kw["alert"] for kw in sent} == {"transient": True, "config": False}
    assert all(kw["replay"] is True for kw in sent)
    rows = _rows()
    assert rows["transient"].auto_replay_count == 1
    assert rows["transient"].last_auto_replay_at is not None
    assert rows["config"].auto_replay_count == 1
    assert rows["permanent"].auto_replay_count == 0


def test_unknown_model_sends_one_canary_and_backoff_blocks_the_next_run(
    mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    _park("a", "transient", TODAY)
    _park("b", "transient", TODAY)
    sent: list[dict] = []
    monkeypatch.setattr("cti_core.celery_client.send_enrich_task", lambda **kw: sent.append(kw))
    monkeypatch.setattr("cti_scraper.sinks.enrich_queue_depth", lambda: 0)

    mod.auto_replay()
    assert len(sent) == 1

    mod.auto_replay()  # `a` masih dalam backoff 60 menit, jadi canary berikutnya = `b`
    assert [kw["title"] for kw in sent] == [
        sent[0]["title"],
        "b" if sent[0]["title"] == "a" else "a",
    ]


def test_send_failure_after_commit_is_counted_not_retried(
    mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    _llm_call(datetime.datetime.now(datetime.UTC))
    _park("x", "json", TODAY)

    def boom(**_kw: object) -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr("cti_core.celery_client.send_enrich_task", boom)
    monkeypatch.setattr("cti_scraper.sinks.enrich_queue_depth", lambda: 0)

    assert mod.auto_replay() == {"sent": 0, "failed": 1}
    assert _rows()["x"].auto_replay_count == 1


def test_purge_calls_task(mod) -> None:
    now = datetime.datetime.now(datetime.UTC)
    _llm_call(now - datetime.timedelta(days=91))
    _llm_call(now - datetime.timedelta(days=1))

    assert mod.purge_calls()["deleted"] >= 1

    with sync_session() as s:
        left = s.execute(select(LlmCall).where(LlmCall.model == MODEL)).scalars().all()
    assert len(left) == 1
