"""Repo `llm_calls` + kolom auto-replay `rejected_articles` di Postgres beneran."""

from __future__ import annotations

import datetime
import importlib.util
import pathlib

from cti_core.db.models.llm_call import LlmCall
from cti_core.db.repositories.article import RejectedArticleRepo
from cti_core.db.repositories.llm_call import AsyncLlmCallRepo, LlmCallRepo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

NOW = datetime.datetime.now(datetime.UTC)


def _add(
    repo: LlmCallRepo,
    task: str,
    status: str = "ok",
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    latency_ms: int = 100,
    prompt_version: str | None = "abcd1234",
) -> None:
    repo.add(
        task=task,
        model="m",
        prompt_version=prompt_version,
        status=status,
        error_type="RateLimitError" if status == "error" else None,
        http_status=429 if status == "error" else None,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
    )


def test_add_and_latest_for_tasks(db_session: Session) -> None:
    repo = LlmCallRepo(db_session)
    _add(repo, "classify")
    _add(repo, "ttp", status="error")
    db_session.flush()
    latest = repo.latest_for_tasks(["classify", "ttp"])
    assert latest is not None
    assert latest.status == "error"
    assert repo.latest_for_tasks(["recap_daily"]) is None


async def test_usage_by_task_sums_known_tokens_only(
    db_session: Session, async_db_session: AsyncSession
) -> None:
    # Dua sesi berbeda tidak berbagi transaksi: tulis lewat sesi async sendiri.
    del db_session
    s = async_db_session
    for status, pt, ct, lat, ver in [
        ("ok", 10, 2, 100, "v1"),
        ("ok", 20, 3, 300, "v1"),
        ("error", None, None, 200, "v1"),
        ("empty", None, None, 50, "v1"),
    ]:
        s.add(
            LlmCall(
                task="classify",
                model="m",
                prompt_version=ver,
                status=status,
                prompt_tokens=pt,
                completion_tokens=ct,
                latency_ms=lat,
            )
        )
    s.add(LlmCall(task="ttp", model="m", status="ok", latency_ms=10))
    await s.flush()
    rows = {
        r.task: r
        for r in await AsyncLlmCallRepo(s).usage_by_task(NOW - datetime.timedelta(hours=1))
    }
    c = rows["classify"]
    assert (c.calls, c.errors) == (4, 2)  # 'error' dan 'empty' sama-sama dihitung
    assert (c.prompt_tokens, c.completion_tokens) == (30, 5)
    assert c.median_latency_ms == 150
    assert c.prompt_version == "v1"
    assert rows["ttp"].prompt_tokens is None
    assert rows["ttp"].completion_tokens is None


async def test_async_latest_helpers(async_db_session: AsyncSession) -> None:
    s = async_db_session
    t0 = NOW - datetime.timedelta(minutes=10)
    s.add(LlmCall(task="classify", model="m", status="ok", latency_ms=1, at=t0))
    s.add(
        LlmCall(
            task="ttp",
            model="m",
            status="error",
            error_type="X",
            latency_ms=1,
            at=t0 + datetime.timedelta(minutes=5),
        )
    )
    await s.flush()
    repo = AsyncLlmCallRepo(s)
    assert await repo.latest_ok_at(["classify", "ttp"]) == t0
    err = await repo.latest_error()
    assert err is not None and err.task == "ttp"
    latest = await repo.latest_for_tasks(["classify", "ttp"])
    assert latest is not None and latest.task == "ttp"
    assert await repo.latest_ok_at(["recap_daily"]) is None


def test_purge_older_than_90_days(db_session: Session) -> None:
    db_session.add(
        LlmCall(
            task="classify",
            model="m",
            status="ok",
            latency_ms=1,
            at=NOW - datetime.timedelta(days=91),
        )
    )
    db_session.add(
        LlmCall(
            task="classify",
            model="m",
            status="ok",
            latency_ms=1,
            at=NOW - datetime.timedelta(days=1),
        )
    )
    db_session.flush()
    assert LlmCallRepo(db_session).purge_older_than(NOW - datetime.timedelta(days=90)) == 1


def test_rejected_upsert_keeps_auto_replay_fields(db_session: Session) -> None:
    repo = RejectedArticleRepo(db_session)
    row = repo.upsert(url="https://example.com/a", title="t", source="s", failure_kind="transient")
    assert row.auto_replay_count == 0
    assert row.last_auto_replay_at is None
    stamp = NOW - datetime.timedelta(minutes=5)
    row.auto_replay_count = 2
    row.last_auto_replay_at = stamp
    db_session.flush()

    again = repo.upsert(url="https://example.com/a", title="t2", source="s", failure_kind="json")
    assert again.id == row.id
    assert again.auto_replay_count == 2
    assert again.last_auto_replay_at == stamp


def test_migration_backfill_config(db_session: Session) -> None:
    path = next(
        p
        for p in (pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions").iterdir()
        if p.name.startswith("c4e7a2b9d1f0_")
    )
    spec = importlib.util.spec_from_file_location("mig_c4e7a2b9d1f0", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    rows = [
        ("h1", "[enrichment_failed] BadRequestError: 400"),
        ("h2", "[enrichment_failed] RateLimitError: 429"),
    ]
    for h, reason in rows:
        db_session.execute(
            text(
                "INSERT INTO rejected_articles (url, url_hash, title, source, reason, failure_kind,"
                " raw_enrichment) VALUES (:u, :h, 't', 's', :r, 'permanent', '{}'::jsonb)"
            ),
            {"u": f"https://x/{h}", "h": h, "r": reason},
        )
    db_session.execute(text(mod.BACKFILL_CONFIG_SQL))
    kinds = dict(
        db_session.execute(
            text(
                "SELECT url_hash, failure_kind FROM rejected_articles WHERE url_hash IN ('h1','h2')"
            )
        ).all()
    )
    assert kinds == {"h1": "config", "h2": "permanent"}
